from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from users_api.core.config import Settings
from users_api.core.errors import ProblemError
from users_api.core.ports import EmailSender, RateLimiter, SessionStore
from users_api.core.security import (
    generate_emailed_token,
    hash_password,
    hash_token,
    verify_password,
)
from users_api.features.auth.domain import User
from users_api.features.auth.repositories import UserRepository
from users_api.features.password_reset.domain import PasswordResetToken
from users_api.features.password_reset.repositories import PasswordResetTokenRepository

RESET_LINK_INVALID = "El link de recuperación es inválido o expiró. Pedí uno nuevo"
SAME_PASSWORD = "La contraseña nueva tiene que ser distinta de la actual"


def reset_request_key(identifier: str) -> str:
    return f"reset:requested:{identifier.strip().lower()}"


@dataclass
class PasswordResetService:
    users: UserRepository
    reset_tokens: PasswordResetTokenRepository
    rate_limiter: RateLimiter
    sessions: SessionStore
    settings: Settings
    email_sender: EmailSender

    async def forgot_password(self, identifier: str) -> None:
        """Send the reset link. Always answers the same.

        The rate limit is counted before looking the account up, and it is
        counted whether or not it exists: a counter that only moved for real
        accounts would turn the limit itself into an oracle telling an attacker
        which addresses are registered.
        """
        await self.guard_reset_limit(identifier)

        user = await self.users.find_by_identifier(identifier.strip().lower())
        if user is None or not user.can_log_in:
            return

        now = datetime.now(UTC)
        raw_token = generate_emailed_token()
        await self.reset_tokens.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hash_token(raw_token),
                # Ten minutes, and not the twenty four hours of the verification
                # link: this one opens the door to the account.
                expires_at=now + timedelta(minutes=self.settings.password_reset_minutes),
            )
        )
        reset_url = f"{self.settings.public_base_url}/auth/reset-password?token={raw_token}"
        await self.email_sender.send_password_reset(to=user.email, reset_url=reset_url)

    async def guard_reset_limit(self, identifier: str) -> None:
        """Cap how many links can be asked for the same identifier.

        Counted by identifier and not by account, which means the same person
        can ask with their email and again with their handle. Sharing one
        counter would need resolving the identifier to an account first, and
        then the 429 would answer whether that account exists.
        """
        requests = await self.rate_limiter.hit(
            reset_request_key(identifier),
            window_seconds=self.settings.password_reset_window_minutes * 60,
        )
        if requests > self.settings.password_reset_max_requests:
            raise ProblemError(
                status=429,
                code="too-many-reset-requests",
                title="Demasiados pedidos",
                detail=(
                    "Se pidieron demasiados links de recuperación. Esperá "
                    f"{self.settings.password_reset_window_minutes} minutos"
                ),
                headers={"Retry-After": str(self.settings.password_reset_window_minutes * 60)},
            )

    async def reset_password(self, raw_token: str, new_password: str) -> User:
        now = datetime.now(UTC)
        token = await self.reset_tokens.find_by_hash(hash_token(raw_token))
        if token is None or not token.is_usable(now):
            # Expired, unknown or already used all answer the same, pointing at
            # asking for a new link.
            raise ProblemError(
                status=400,
                code="reset-token-invalid",
                title="No se pudo cambiar la contraseña",
                detail=RESET_LINK_INVALID,
            )

        user = await self.users.get(token.user_id)

        # Checked against the stored hash before replacing it.
        if verify_password(new_password, user.password_hash):
            raise ProblemError(
                status=400,
                code="password-unchanged",
                title="No se pudo cambiar la contraseña",
                detail=SAME_PASSWORD,
            )

        user.password_hash = hash_password(new_password)
        await self.users.update(user)

        # The consumed link dies, and so does every other open link of this
        # account. Otherwise one sent minutes earlier would still be a way in
        # after the password already changed.
        await self.reset_tokens.mark_all_used(user.id, used_at=now)

        await self.sessions.revoke_all(
            user.id,
            now=now,
            ttl_seconds=self.settings.access_token_minutes * 60,
        )
        return user
