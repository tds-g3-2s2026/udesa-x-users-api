from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from users_api.core.config import Settings
from users_api.core.errors import ProblemError
from users_api.core.ports import EmailSender, RateLimiter, SessionStore
from users_api.core.security import (
    decode_access_token,
    generate_emailed_token,
    hash_password,
    hash_token,
    issue_access_token,
    verify_password,
)
from users_api.features.auth.domain import EmailVerificationToken, User
from users_api.features.auth.repositories import (
    EmailVerificationTokenRepository,
    UserRepository,
)

# The same message for a missing account and a wrong password, so the response
# never tells an attacker which accounts exist.
INVALID_CREDENTIALS = "Credenciales inválidas"
SUSPENDED_ACCOUNT = "Cuenta suspendida"
UNVERIFIED_ACCOUNT = "Revisá tu casilla de correo para validar la cuenta antes de ingresar"
INVALID_TOKEN = "El token no es válido"


def lockout_key(identifier: str) -> str:
    return f"login:failed:{identifier.strip().lower()}"


@dataclass
class AuthService:
    """Registration, login and logout.

    Everything it needs from the outside arrives as an interface, so this class
    never names a database, a cache or a mail provider. That is what makes it
    testable without infrastructure and movable without a rewrite.
    """

    users: UserRepository
    verification_tokens: EmailVerificationTokenRepository
    rate_limiter: RateLimiter
    sessions: SessionStore
    settings: Settings
    signing_key: object
    email_sender: EmailSender

    async def register(self, *, email: str, handle: str, password: str) -> User:
        # Normalising before storing is what makes uniqueness case-insensitive,
        # so Alumno@udesa.edu.ar collides with alumno@udesa.edu.ar.
        normalised_email = email.strip().lower()
        normalised_handle = handle.strip().lower()

        if await self.users.exists_with_email_or_handle(normalised_email, normalised_handle):
            # The message does not say which of the two collided, to avoid
            # turning registration into an account oracle.
            raise ProblemError(
                status=409,
                code="account-already-exists",
                title="No se pudo crear la cuenta",
                detail="El email o el nombre de usuario ya están en uso",
            )

        now = datetime.now(UTC)
        user = await self.users.add(
            User(
                email=normalised_email,
                handle=normalised_handle,
                password_hash=hash_password(password),
                is_email_verified=False,
                terms_accepted=True,
                terms_accepted_at=now,
            )
        )

        await self.issue_verification_token(user, now=now)
        return user

    async def issue_verification_token(self, user: User, *, now: datetime) -> str:
        raw_token = generate_emailed_token()
        await self.verification_tokens.add(
            EmailVerificationToken(
                user_id=user.id,
                token_hash=hash_token(raw_token),
                # The link stops working after the configured window.
                expires_at=now + timedelta(hours=self.settings.email_verification_hours),
            )
        )
        verification_url = f"{self.settings.public_base_url}/auth/verify?token={raw_token}"
        await self.email_sender.send_verification(to=user.email, verification_url=verification_url)
        return raw_token

    async def verify_email(self, raw_token: str) -> User:
        now = datetime.now(UTC)
        token = await self.verification_tokens.find_by_hash(hash_token(raw_token))
        if token is None or not token.is_usable(now):
            # An expired or already used token is refused, and the user is
            # pointed at the resend endpoint.
            raise ProblemError(
                status=400,
                code="verification-token-invalid",
                title="No se pudo validar la cuenta",
                detail="El link de validación es inválido o expiró. Pedí uno nuevo desde el login",
            )

        await self.verification_tokens.mark_used(token.id, used_at=now)
        user = await self.users.get(token.user_id)
        user.is_email_verified = True
        await self.users.update(user)
        return user

    async def resend_verification(self, email: str) -> None:
        """Re-send the verification link. Always answers the same.

        Telling the caller whether the address is registered would leak the same
        information the login endpoint is careful to hide.
        """
        user = await self.users.find_by_email(email.strip().lower())
        if user is None or user.is_email_verified or not user.can_log_in:
            return
        await self.issue_verification_token(user, now=datetime.now(UTC))

    async def login(self, *, identifier: str, password: str) -> tuple[str, int]:
        await self.guard_lockout(identifier)

        user = await self.users.find_by_identifier(identifier.strip().lower())

        # The password is always verified, even when the account does not exist,
        # so the response time does not reveal which accounts are registered.
        if not verify_password(password, user.password_hash if user else None):
            await self.register_failure(identifier)
            raise ProblemError(
                status=401,
                code="invalid-credentials",
                title="No se pudo iniciar sesión",
                detail=INVALID_CREDENTIALS,
            )

        # Only now, with the password proven, is the account state revealed. The
        # caller already showed they own the account, so these messages can be
        # specific without becoming an enumeration vector.
        if not user.can_log_in:
            raise ProblemError(
                status=403,
                code="account-suspended",
                title="No se pudo iniciar sesión",
                detail=SUSPENDED_ACCOUNT,
            )

        if not user.is_email_verified:
            raise ProblemError(
                status=403,
                code="account-not-verified",
                title="No se pudo iniciar sesión",
                detail=UNVERIFIED_ACCOUNT,
            )

        await self.rate_limiter.reset(lockout_key(identifier))
        token = issue_access_token(
            self.signing_key,
            subject=user.id,
            role="user",
            expires_in_minutes=self.settings.access_token_minutes,
        )
        return token, self.settings.access_token_minutes * 60

    async def guard_lockout(self, identifier: str) -> None:
        failures = await self.rate_limiter.count(lockout_key(identifier))
        if failures >= self.settings.login_max_attempts:
            # 429 and not 401: what is being rejected is the rate, not the
            # credentials.
            raise ProblemError(
                status=429,
                code="too-many-attempts",
                title="Demasiados intentos",
                detail=(
                    "La cuenta quedó bloqueada temporalmente por "
                    f"{self.settings.login_lockout_minutes} minutos"
                ),
                headers={"Retry-After": str(self.settings.login_lockout_minutes * 60)},
            )

    async def register_failure(self, identifier: str) -> None:
        """Count the failure and start the window on the first one.

        The counter is keyed by identifier and not by account id, so attempts
        against addresses that do not exist are counted the same way.
        """
        await self.rate_limiter.hit(
            lockout_key(identifier),
            window_seconds=self.settings.login_lockout_minutes * 60,
        )

    async def logout(self, token: str) -> None:
        """Revoke the token that was used to call this.

        A JWT is self-contained and the server never stored it, so logging out
        means recording its jti as revoked until it would have expired anyway.
        """
        try:
            claims = decode_access_token(self.signing_key.public_key(), token)
        except jwt.ExpiredSignatureError:
            # Already unusable on its own; revoking it changes nothing, so this
            # is not an error. Logout is idempotent.
            return
        except jwt.InvalidTokenError as exc:
            raise ProblemError(
                status=401,
                code="invalid-token",
                title="No se pudo cerrar la sesión",
                detail=INVALID_TOKEN,
            ) from exc

        await self.sessions.revoke_token(
            claims["jti"],
            expires_at=datetime.fromtimestamp(claims["exp"], tz=UTC),
            now=datetime.now(UTC),
        )
