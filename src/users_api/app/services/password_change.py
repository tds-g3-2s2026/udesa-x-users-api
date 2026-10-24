"""Changing a password that the owner still knows.

The twin of `password_reset`, with the first step swapped: there ownership is
proven by a token that arrived by email, here by typing the current password.
From that point on both do the same thing: the new password answers to the same
rules, and succeeding revokes every session of the account.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from users_api.app.clients.email import EmailSender
from users_api.app.errors import ProblemError
from users_api.app.models.user import User
from users_api.app.repositories.rate_limiter import RateLimiter
from users_api.app.repositories.sessions import SessionStore
from users_api.app.repositories.tokens import RefreshTokenRepository
from users_api.app.repositories.users import UserRepository
from users_api.app.security import hash_password, verify_password
from users_api.app.services.current_password import CurrentPasswordCheck
from users_api.app.services.password_reset import SAME_PASSWORD
from users_api.config.settings import Settings

CHANGE_FAILED_TITLE = "No se pudo cambiar la contraseña"


@dataclass
class PasswordChangeService:
    users: UserRepository
    refresh_tokens: RefreshTokenRepository
    rate_limiter: RateLimiter
    sessions: SessionStore
    settings: Settings
    email_sender: EmailSender

    @property
    def current_password_check(self) -> CurrentPasswordCheck:
        return CurrentPasswordCheck(rate_limiter=self.rate_limiter, settings=self.settings)

    async def change_password(
        self, user: User, *, current_password: str, new_password: str
    ) -> None:
        check = self.current_password_check
        await check.verify(user, current_password, title=CHANGE_FAILED_TITLE)

        # The same rule the reset applies, with the same message.
        if verify_password(new_password, user.password_hash):
            raise ProblemError(
                status=400,
                code="password-unchanged",
                title=CHANGE_FAILED_TITLE,
                detail=SAME_PASSWORD,
            )

        user.password_hash = hash_password(new_password)
        # Whatever brought the account here, from this point on the password
        # is one the owner chose. The deadline goes with it: leaving the date
        # behind would have the panel show an expiry for a password that is
        # no longer temporary.
        user.must_change_password = False
        user.temporary_password_expires_at = None
        await self.users.update(user)
        await check.reset(user)

        # The cutoff is now, so the token this request arrived with
        # is on the wrong side of it too and stops working right here. This
        # runs on Redis, outside the request's transaction, and before that
        # transaction commits: the security guarantee is made to hold even if
        # something below fails.
        now = datetime.now(UTC)
        await self.sessions.revoke_all(
            user.id,
            now=now,
            ttl_seconds=self.settings.access_token_minutes * 60,
        )
        # That cutoff stops mattering once the access tokens it covers expire,
        # and a refresh token lasts days: left open, it would hand out working
        # sessions again to whoever held it before the password changed.
        await self.refresh_tokens.revoke_all(user.id, revoked_at=now)

        # Sent last, and only once everything else went through, so
        # a failed change never warns about a change that did not happen.
        await self.email_sender.send_password_changed(to=user.email)
