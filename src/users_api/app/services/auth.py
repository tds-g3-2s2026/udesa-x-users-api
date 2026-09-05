from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from users_api.app.clients.email import EmailSender
from users_api.app.errors import ProblemError
from users_api.app.models.tokens import EmailVerificationToken
from users_api.app.models.user import User
from users_api.app.repositories.rate_limiter import RateLimiter
from users_api.app.repositories.sessions import SessionStore
from users_api.app.repositories.tokens import EmailVerificationTokenRepository
from users_api.app.repositories.users import UserRepository
from users_api.app.security import (
    decode_access_token,
    generate_emailed_token,
    hash_password,
    hash_token,
    issue_access_token,
    verify_password,
)
from users_api.config.settings import Settings

# The same message for a missing account and a wrong password, so the response
# never tells an attacker which accounts exist.
INVALID_CREDENTIALS = "Credenciales inválidas"
SUSPENDED_ACCOUNT = "Cuenta suspendida"
UNVERIFIED_ACCOUNT = "Revisá tu casilla de correo para validar la cuenta antes de ingresar"
INVALID_TOKEN = "El token no es válido"
NOT_AN_ADMINISTRATOR = "Esta cuenta no tiene acceso al backoffice"


@dataclass(frozen=True)
class LoginPolicy:
    """How many failures a door tolerates, and for how long it then stays shut.

    The app and the backoffice are two doors with two policies (T-26). Each has
    its own key prefix, so failing at one never counts against the other.
    """

    key_prefix: str
    max_attempts: int
    lockout_minutes: int

    def key(self, identifier: str) -> str:
        return f"{self.key_prefix}:failed:{identifier.strip().lower()}"

    @property
    def window_seconds(self) -> int:
        return self.lockout_minutes * 60


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

    @property
    def app_login_policy(self) -> LoginPolicy:
        return LoginPolicy(
            key_prefix="login",
            max_attempts=self.settings.login_max_attempts,
            lockout_minutes=self.settings.login_lockout_minutes,
        )

    @property
    def admin_login_policy(self) -> LoginPolicy:
        return LoginPolicy(
            key_prefix="admin-login",
            max_attempts=self.settings.admin_login_max_attempts,
            lockout_minutes=self.settings.admin_login_lockout_minutes,
        )

    async def login(self, *, identifier: str, password: str) -> tuple[str, int]:
        policy = self.app_login_policy
        await self.guard_lockout(identifier, policy)

        user = await self.users.find_by_identifier(identifier.strip().lower())

        # The password is always verified, even when the account does not exist,
        # so the response time does not reveal which accounts are registered.
        if not verify_password(password, user.password_hash if user else None):
            await self.register_failure(identifier, policy)
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

        await self.rate_limiter.reset(policy.key(identifier))
        return self.issue_session(user)

    async def admin_login(self, *, email: str, password: str) -> tuple[str, int]:
        """The backoffice door: same credentials, stricter policy, role required.

        Administrators are created by a superadmin or seeded, never
        self-registered, so there is no email verification to check here.
        """
        policy = self.admin_login_policy
        await self.guard_lockout(email, policy)

        user = await self.users.find_by_email(email.strip().lower())

        if not verify_password(password, user.password_hash if user else None):
            await self.register_failure(email, policy)
            raise ProblemError(
                status=401,
                code="invalid-credentials",
                title="No se pudo iniciar sesión",
                detail=INVALID_CREDENTIALS,
            )

        # 403 and not 401: the caller proved they own the account, what they lack
        # is the permission. Not counted as a failure either, since a correct
        # password is not a brute force signal.
        if not user.is_administrator:
            raise ProblemError(
                status=403,
                code="not-an-administrator",
                title="No se pudo iniciar sesión",
                detail=NOT_AN_ADMINISTRATOR,
            )

        if not user.can_log_in:
            raise ProblemError(
                status=403,
                code="account-suspended",
                title="No se pudo iniciar sesión",
                detail=SUSPENDED_ACCOUNT,
            )

        await self.rate_limiter.reset(policy.key(email))
        return self.issue_session(user)

    def issue_session(self, user: User) -> tuple[str, int]:
        token = issue_access_token(
            self.signing_key,
            subject=user.id,
            role=user.role.value,
            expires_in_minutes=self.settings.access_token_minutes,
        )
        return token, self.settings.access_token_minutes * 60

    async def guard_lockout(self, identifier: str, policy: LoginPolicy) -> None:
        failures = await self.rate_limiter.count(policy.key(identifier))
        if failures >= policy.max_attempts:
            # 429 and not 401: what is being rejected is the rate, not the
            # credentials.
            raise ProblemError(
                status=429,
                code="too-many-attempts",
                title="Demasiados intentos",
                detail=(
                    f"La cuenta quedó bloqueada temporalmente por {policy.lockout_minutes} minutos"
                ),
                headers={"Retry-After": str(policy.window_seconds)},
            )

    async def register_failure(self, identifier: str, policy: LoginPolicy) -> None:
        """Count the failure and start the window on the first one.

        The counter is keyed by identifier and not by account id, so attempts
        against addresses that do not exist are counted the same way.
        """
        await self.rate_limiter.hit(policy.key(identifier), window_seconds=policy.window_seconds)

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
