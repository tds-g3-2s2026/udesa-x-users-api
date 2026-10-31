"""Closing an account on its owner's request."""

from dataclasses import dataclass
from datetime import UTC, datetime

from users_api.app import events
from users_api.app.errors import ProblemError
from users_api.app.models.user import User
from users_api.app.repositories.outbox import OutboxRepository
from users_api.app.repositories.rate_limiter import RateLimiter
from users_api.app.repositories.sessions import SessionStore
from users_api.app.repositories.tokens import RefreshTokenRepository
from users_api.app.repositories.users import UserRepository
from users_api.app.services.current_password import CurrentPasswordCheck
from users_api.config.settings import Settings

DELETION_FAILED_TITLE = "No se pudo dar de baja la cuenta"


@dataclass
class AccountDeletionService:
    users: UserRepository
    refresh_tokens: RefreshTokenRepository
    rate_limiter: RateLimiter
    sessions: SessionStore
    settings: Settings
    outbox: OutboxRepository

    @property
    def current_password_check(self) -> CurrentPasswordCheck:
        return CurrentPasswordCheck(rate_limiter=self.rate_limiter, settings=self.settings)

    async def delete_account(self, user: User, *, current_password: str) -> None:
        """Mark the account as deleted and end every session it has.

        The row stays: other tables point at it, and a soft delete keeps those
        references valid. Its email and handle stay reserved with it, so they
        cannot be registered again.

        The failed attempts are not reset on success: the account is gone and
        the counter expires on its own.
        """
        # Asked before the password, so a refusal that has nothing to do with it
        # does not spend one of the attempts. 403 and not 400: the caller is who
        # they say, what they lack is the permission. Administrators are managed
        # from the backoffice, and this route would let the last superadmin close
        # the only door into it.
        if user.is_administrator:
            raise ProblemError(
                status=403,
                code="administrator-cannot-delete-account",
                title=DELETION_FAILED_TITLE,
                detail="Las cuentas de administrador no se dan de baja desde la app",
            )

        await self.current_password_check.verify(
            user, current_password, title=DELETION_FAILED_TITLE
        )

        now = datetime.now(UTC)
        user.deleted_at = now
        await self.users.update(user)
        # The same `now` as the mark above, so the event says when the account
        # was closed and not when somebody got round to publishing it. It
        # commits or rolls back with the mark: the account is never closed
        # without its event, and the event never describes a closing that did
        # not happen.
        await self.outbox.add(events.user_deleted(user, now=now))

        # Same as when the password changes. The cutoff is now, so the token
        # this request arrived with is on the wrong side of it too, and the app
        # does not have to log out afterwards. It runs on Redis, outside the
        # request's transaction.
        await self.sessions.revoke_all(
            user.id,
            now=now,
            ttl_seconds=self.settings.access_token_minutes * 60,
        )
        # That cutoff stops mattering once the access tokens it covers expire,
        # and a refresh token lasts days. The account is refused on refresh
        # anyway, but a token left open is a credential nobody can account for.
        await self.refresh_tokens.revoke_all(user.id, revoked_at=now)
