"""Proving that whoever holds a session also knows the account's password.

A session token can sit on an unlocked phone, so the operations that cannot be
undone, or that change who owns the account, ask for the current password
again. They all share one budget of wrong attempts: if each kept a counter of
its own, someone alternating between them would get a fresh set of guesses every
time and the limit would stop being a limit.
"""

from dataclasses import dataclass

from users_api.app.errors import ProblemError
from users_api.app.models.user import User
from users_api.app.repositories.rate_limiter import RateLimiter
from users_api.app.security import verify_password
from users_api.app.services.auth import LoginPolicy
from users_api.config.settings import Settings

CURRENT_PASSWORD_INVALID = "La contraseña actual no es correcta"


@dataclass
class CurrentPasswordCheck:
    rate_limiter: RateLimiter
    settings: Settings

    @property
    def policy(self) -> LoginPolicy:
        """Three attempts and fifteen minutes, counted apart from the login.

        The same parametrised limiter the login doors use, with a prefix of its
        own: what gets shut is these operations, and signing in keeps working.
        Locking sign-in as well would hand whoever picks up an unlocked phone a
        way to keep the owner out of their own account, and out of the recovery
        flow they would need from another device.

        The prefix and the settings keep the name they had when changing the
        password was the only operation using them. Renaming them would reset
        live counters and break deployed configuration for no gain.
        """
        return LoginPolicy(
            key_prefix="change-password",
            max_attempts=self.settings.change_password_max_attempts,
            lockout_minutes=self.settings.change_password_lockout_minutes,
        )

    async def verify(self, user: User, current_password: str, *, title: str) -> None:
        """Raise unless the password is right and attempts are left.

        `title` is the caller's, so the error reads as a failure of the
        operation the user was attempting and not of a generic check.
        """
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
                title=title,
                detail=CURRENT_PASSWORD_INVALID,
            )

    async def reset(self, user: User) -> None:
        """Forget the failed attempts once the operation went through."""
        await self.rate_limiter.reset(self.policy.key(str(user.id)))

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
                    f"Volvé a intentarlo en {policy.lockout_minutes} minutos"
                ),
                headers={"Retry-After": str(policy.window_seconds)},
            )
