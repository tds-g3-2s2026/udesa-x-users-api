import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from redis.asyncio import Redis
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from users_api import rate_limit
from users_api.config import Settings
from users_api.email import EmailSender
from users_api.errors import ProblemError
from users_api.models import EmailVerificationToken, PasswordResetToken, User
from users_api.security import (
    decode_access_token,
    generate_verification_token,
    hash_password,
    hash_token,
    issue_access_token,
    verify_password,
)

# Same message for a missing account and a wrong password, so the response never
# tells an attacker which accounts exist. E1-H2 CA.3.
INVALID_CREDENTIALS = "Credenciales inválidas"
SUSPENDED_ACCOUNT = "Cuenta suspendida"
UNVERIFIED_ACCOUNT = "Revisá tu casilla de correo para validar la cuenta antes de ingresar"
INVALID_TOKEN = "El token no es válido"
RESET_LINK_INVALID = "El link de recuperación es inválido o expiró. Pedí uno nuevo"
SAME_PASSWORD = "La contraseña nueva tiene que ser distinta de la actual"


def lockout_key(identifier: str) -> str:
    return f"login:failed:{identifier.strip().lower()}"


def revoked_key(jti: str) -> str:
    return f"revoked:jti:{jti}"


def sessions_revoked_key(user_id: uuid.UUID) -> str:
    """Marks the moment every session of an account stopped being valid.

    The jti list above revokes one token; this revokes all of them at once,
    which is what E1-H5 CA.7 needs. They are different mechanisms because the
    service never stored the tokens it issued, so there is no list of jtis to
    walk: what gets compared is the iat of each token against this instant.
    """
    return f"revoked:user:{user_id}"


def reset_request_key(identifier: str) -> str:
    return f"reset:requested:{identifier.strip().lower()}"


@dataclass
class AuthService:
    session: AsyncSession
    redis: Redis
    settings: Settings
    signing_key: object
    email_sender: EmailSender

    # --- registration, E1-H1 ---------------------------------------------

    async def register(self, *, email: str, handle: str, password: str) -> User:
        # E1-H1 CA.7: normalising before storing is what makes uniqueness
        # case-insensitive, so Alumno@udesa.edu.ar collides with alumno@udesa.edu.ar.
        normalised_email = email.strip().lower()
        normalised_handle = handle.strip().lower()

        taken = await self.session.scalar(
            select(User).where(
                or_(User.email == normalised_email, User.handle == normalised_handle)
            )
        )
        if taken is not None:
            # E1-H1 CA.2 and CA.3. The message does not say which of the two
            # collided, to avoid turning registration into an account oracle.
            raise ProblemError(
                status=409,
                code="account-already-exists",
                title="No se pudo crear la cuenta",
                detail="El email o el nombre de usuario ya están en uso",
            )

        now = datetime.now(UTC)
        user = User(
            email=normalised_email,
            handle=normalised_handle,
            password_hash=hash_password(password),
            is_email_verified=False,
            terms_accepted=True,
            terms_accepted_at=now,
        )
        self.session.add(user)
        await self.session.flush()

        await self.issue_verification_token(user, now=now)
        return user

    async def issue_verification_token(self, user: User, *, now: datetime) -> str:
        raw_token = generate_verification_token()
        self.session.add(
            EmailVerificationToken(
                user_id=user.id,
                token_hash=hash_token(raw_token),
                # E1-H1 CA.6: the link stops working after the configured window.
                expires_at=now + timedelta(hours=self.settings.email_verification_hours),
            )
        )
        verification_url = f"{self.settings.public_base_url}/auth/verify?token={raw_token}"
        await self.email_sender.send_verification(to=user.email, verification_url=verification_url)
        return raw_token

    async def verify_email(self, raw_token: str) -> User:
        now = datetime.now(UTC)
        token = await self.session.scalar(
            select(EmailVerificationToken).where(
                EmailVerificationToken.token_hash == hash_token(raw_token)
            )
        )
        if token is None or not token.is_usable(now):
            # E1-H1 CA.6: an expired or already used token is refused, and the
            # user is pointed at the resend endpoint.
            raise ProblemError(
                status=400,
                code="verification-token-invalid",
                title="No se pudo validar la cuenta",
                detail="El link de validación es inválido o expiró. Pedí uno nuevo desde el login",
            )

        token.used_at = now
        user = await self.session.get(User, token.user_id)
        user.is_email_verified = True
        return user

    async def resend_verification(self, email: str) -> None:
        """Re-send the verification link. Always answers the same.

        Telling the caller whether the address is registered would leak the same
        information the login endpoint is careful to hide.
        """
        user = await self.session.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None or user.is_email_verified or not user.can_log_in:
            return
        await self.issue_verification_token(user, now=datetime.now(UTC))

    # --- login, E1-H2 -----------------------------------------------------

    async def login(self, *, identifier: str, password: str) -> tuple[str, int]:
        await self.guard_lockout(identifier)

        normalised = identifier.strip().lower()
        user = await self.session.scalar(
            select(User).where(or_(User.email == normalised, User.handle == normalised))
        )

        # The password is always verified, even when the account does not exist,
        # so timing does not reveal it. E1-H2 CA.3.
        if not verify_password(password, user.password_hash if user else None):
            await self.register_failure(identifier)
            raise ProblemError(
                status=401,
                code="invalid-credentials",
                title="No se pudo iniciar sesión",
                detail=INVALID_CREDENTIALS,
            )

        # Only now, with the password proven, is the account state revealed. The
        # caller already showed they own the account, so CA.4 and CA.5 can be
        # specific without becoming an enumeration vector.
        if not user.can_log_in:
            # E1-H2 CA.5: suspended by an admin, or soft-deleted by the user.
            raise ProblemError(
                status=403,
                code="account-suspended",
                title="No se pudo iniciar sesión",
                detail=SUSPENDED_ACCOUNT,
            )

        if not user.is_email_verified:
            # E1-H1 CA.1 and E1-H2 CA.4.
            raise ProblemError(
                status=403,
                code="account-not-verified",
                title="No se pudo iniciar sesión",
                detail=UNVERIFIED_ACCOUNT,
            )

        await rate_limit.reset(self.redis, lockout_key(identifier))
        token = issue_access_token(
            self.signing_key,
            subject=user.id,
            role="user",
            expires_in_minutes=self.settings.access_token_minutes,
        )
        return token, self.settings.access_token_minutes * 60

    async def guard_lockout(self, identifier: str) -> None:
        failures = await rate_limit.count(self.redis, lockout_key(identifier))
        if failures >= self.settings.login_max_attempts:
            # E1-H2 CA.2. 429 and not 401: what is being rejected is the rate,
            # not the credentials.
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
        await rate_limit.hit(
            self.redis,
            lockout_key(identifier),
            window_seconds=self.settings.login_lockout_minutes * 60,
        )

    # --- logout, E1-H3 ------------------------------------------------------

    async def logout(self, token: str) -> None:
        """Revoke the token's jti, E1-H3 CA.1.

        A JWT is self-contained and the server never stored it, so "logging out"
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

        expires_at = datetime.fromtimestamp(claims["exp"], tz=UTC)
        ttl = int((expires_at - datetime.now(UTC)).total_seconds())
        await self.redis.set(revoked_key(claims["jti"]), "1", ex=ttl)

    async def revoke_all_sessions(self, user_id: uuid.UUID, *, now: datetime) -> None:
        """Invalidate every token issued for this account before now.

        E1-H5 CA.7 and, later, E1-H13 CA.3 need the same thing, so this lives on
        its own instead of inline in the reset. The TTL is the lifetime of an
        access token: past that there is nothing left to revoke, because every
        token issued before this instant already expired on its own.
        """
        await self.redis.set(
            sessions_revoked_key(user_id),
            int(now.timestamp()),
            ex=self.settings.access_token_minutes * 60,
        )

    # --- password reset, E1-H5 ----------------------------------------------

    async def forgot_password(self, identifier: str) -> None:
        """Send the reset link. Always answers the same, E1-H5 CA.4.

        The rate limit is counted before looking the account up, and it is
        counted whether or not it exists: a counter that only moved for real
        accounts would turn the limit itself into the enumeration oracle that
        CA.4 is avoiding.
        """
        await self.guard_reset_limit(identifier)

        normalised = identifier.strip().lower()
        user = await self.session.scalar(
            select(User).where(or_(User.email == normalised, User.handle == normalised))
        )
        if user is None or not user.can_log_in:
            return

        now = datetime.now(UTC)
        raw_token = generate_verification_token()
        self.session.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hash_token(raw_token),
                # E1-H5 CA.1: ten minutes, and not the twenty four hours of the
                # verification link: this one opens the door to the account.
                expires_at=now + timedelta(minutes=self.settings.password_reset_minutes),
            )
        )
        reset_url = f"{self.settings.public_base_url}/auth/reset-password?token={raw_token}"
        await self.email_sender.send_password_reset(to=user.email, reset_url=reset_url)

    async def guard_reset_limit(self, identifier: str) -> None:
        """E1-H5 CA.8: cap how many links can be asked for the same identifier."""
        requests = await rate_limit.hit(
            self.redis,
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
        token = await self.session.scalar(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(raw_token))
        )
        if token is None or not token.is_usable(now):
            # E1-H5 CA.2 and CA.5: expired, unknown or already used all answer
            # the same, pointing at asking for a new link.
            raise ProblemError(
                status=400,
                code="reset-token-invalid",
                title="No se pudo cambiar la contraseña",
                detail=RESET_LINK_INVALID,
            )

        user = await self.session.get(User, token.user_id)

        # E1-H5 CA.6, checked against the stored hash before replacing it.
        if verify_password(new_password, user.password_hash):
            raise ProblemError(
                status=400,
                code="password-unchanged",
                title="No se pudo cambiar la contraseña",
                detail=SAME_PASSWORD,
            )

        user.password_hash = hash_password(new_password)

        # E1-H5 CA.5: the consumed link dies, and so does every other open link
        # of this account. Otherwise a second link sent minutes earlier would
        # still be a way in after the password already changed.
        await self.session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=now)
        )

        # E1-H5 CA.7.
        await self.revoke_all_sessions(user.id, now=now)
        return user
