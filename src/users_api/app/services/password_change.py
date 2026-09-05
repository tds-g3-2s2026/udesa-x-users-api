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
from users_api.app.repositories.users import UserRepository
from users_api.app.security import hash_password, verify_password
from users_api.app.services.auth import LoginPolicy
from users_api.app.services.password_reset import SAME_PASSWORD
from users_api.config.settings import Settings

CURRENT_PASSWORD_INVALID = "La contraseña actual no es correcta"


@dataclass
class PasswordChangeService:
    users: UserRepository
    rate_limiter: RateLimiter
    sessions: SessionStore
    settings: Settings
    email_sender: EmailSender

    @property
    def policy(self) -> LoginPolicy:
        """Three attempts and fifteen minutes.

        The same parametrised limiter the two login doors use, with a prefix of
        its own: what gets shut is this operation, and signing in keeps working.

        The rule that asks for a temporary lock here is worded exactly like the
        one the login already satisfies, and there it was implemented as a
        counter over the operation being protected, with no locked flag on the
        account: reusing that logic is precisely this. Locking sign-in as well
        would hand whoever picks up an unlocked phone a way to keep the owner
        out of their own account, and out of the recovery flow they would need
        from another device.
        """
        return LoginPolicy(
            key_prefix="change-password",
            max_attempts=self.settings.change_password_max_attempts,
            lockout_minutes=self.settings.change_password_lockout_minutes,
        )

    async def change_password(
        self, user: User, *, current_password: str, new_password: str
    ) -> None:
        policy = self.policy
        # Keyed by account id and not by what was typed: the caller is already
        # authenticated, so there is nothing to guess about who they are.
        identifier = str(user.id)
        await self.guard_lockout(identifier, policy)

        if not verify_password(current_password, user.password_hash):
            await self.rate_limiter.hit(
                policy.key(identifier), window_seconds=policy.window_seconds
            )
            # 400 and not 401: the token in the header is valid, what failed is a
            # field of the body. A 401 here would read as an expired session and
            # push the app to sign the user out for a typo.
            raise ProblemError(
                status=400,
                code="invalid-current-password",
                title="No se pudo cambiar la contraseña",
                detail=CURRENT_PASSWORD_INVALID,
            )

        # The same rule the reset applies, with the same message.
        if verify_password(new_password, user.password_hash):
            raise ProblemError(
                status=400,
                code="password-unchanged",
                title="No se pudo cambiar la contraseña",
                detail=SAME_PASSWORD,
            )

        user.password_hash = hash_password(new_password)
        await self.users.update(user)
        await self.rate_limiter.reset(policy.key(identifier))

        # The cutoff is now, so the token this request arrived with
        # is on the wrong side of it too and stops working right here.
        await self.sessions.revoke_all(
            user.id,
            now=datetime.now(UTC),
            ttl_seconds=self.settings.access_token_minutes * 60,
        )

        # Sent last, and only once everything else went through, so
        # a failed change never warns about a change that did not happen.
        await self.email_sender.send_password_changed(to=user.email)

    async def guard_lockout(self, identifier: str, policy: LoginPolicy) -> None:
        failures = await self.rate_limiter.count(policy.key(identifier))
        if failures >= policy.max_attempts:
            # Identifier of its own, and not the `too-many-attempts` of the
            # login: what is shut here is this operation, not the account. The
            # session stays open and signing in keeps working, so reusing the
            # login identifier would have the client show a message that is
            # plainly false, and force it to tell the two apart by `instance`.
            raise ProblemError(
                status=429,
                code="too-many-password-attempts",
                title="Demasiados intentos",
                detail=(
                    "Erraste la contraseña actual demasiadas veces. "
                    f"Volvé a intentar el cambio en {policy.lockout_minutes} minutos"
                ),
                headers={"Retry-After": str(policy.window_seconds)},
            )
