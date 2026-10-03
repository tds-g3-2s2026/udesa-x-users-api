import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn

import jwt

from users_api.app.clients.email import EmailSender
from users_api.app.errors import ProblemError
from users_api.app.models.tokens import EmailVerificationToken, RefreshToken
from users_api.app.models.user import AccountStatus, User
from users_api.app.repositories.rate_limiter import RateLimiter
from users_api.app.repositories.sessions import SessionStore
from users_api.app.repositories.tokens import (
    EmailVerificationTokenRepository,
    RefreshTokenRepository,
)
from users_api.app.repositories.users import UserRepository
from users_api.app.security import (
    decode_access_token,
    generate_emailed_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    issue_access_token,
    verify_password,
)
from users_api.config.settings import API_PREFIX, Settings

# The same message for a missing account and a wrong password, so the response
# never tells an attacker which accounts exist.
INVALID_CREDENTIALS = "Credenciales inválidas"
SUSPENDED_ACCOUNT = "Cuenta suspendida"
UNDER_REVIEW_ACCOUNT = (
    "Tu cuenta está en revisión por denuncias de otros usuarios. "
    "Mientras dure la revisión no podés iniciar sesión"
)
UNVERIFIED_ACCOUNT = "Revisá tu casilla de correo para validar la cuenta antes de ingresar"
INVALID_TOKEN = "El token no es válido"
NOT_AN_ADMINISTRATOR = "Esta cuenta no tiene acceso al backoffice"
EXPIRED_TEMPORARY_PASSWORD = (
    "La contraseña temporal venció. Pedile al superadministrador que genere una nueva"
)

# One message for every way a refresh token can fail, so the answer never tells
# a thief whether a copy of the token was recognised, expired or already used.
REFRESH_FAILED_TITLE = "No se pudo renovar la sesión"
REFRESH_FAILED_DETAIL = "Tu sesión venció. Iniciá sesión de nuevo"


class InvalidRefreshTokenError(ProblemError):
    def __init__(self) -> None:
        super().__init__(
            status=401,
            code="invalid-refresh-token",
            title=REFRESH_FAILED_TITLE,
            detail=REFRESH_FAILED_DETAIL,
        )


class ReusedRefreshTokenError(InvalidRefreshTokenError):
    """The same answer as any refused token, but the refusal left writes behind.

    It is its own class because the route has to tell it apart: raising rolls
    the request's transaction back, and with it the revocation of the account's
    refresh tokens that detecting the reuse just wrote. The route answers with
    the problem instead of raising it, so that transaction still commits.
    """


@dataclass(frozen=True)
class IssuedSession:
    access_token: str
    refresh_token: str
    expires_in: int


def deny_blocked_account(user: User, *, title: str) -> None:
    """Refuse an account that may not be used, saying why.

    Shared by both logins and by every authenticated request, so a state that
    blocks the login also ends the sessions already open, with the same words.
    Suspension wins over review: a deleted account says suspended whatever its
    status, as CA.5 of E1-H2 asks.
    """
    if user.can_log_in:
        return
    if user.status is AccountStatus.UNDER_REVIEW and user.deleted_at is None:
        # Its own code, so the app can tell the owner the account is waiting
        # for a person to look at it and not closed for good.
        raise ProblemError(
            status=403,
            code="account-under-review",
            title=title,
            detail=UNDER_REVIEW_ACCOUNT,
        )
    raise ProblemError(
        status=403,
        code="account-suspended",
        title=title,
        detail=SUSPENDED_ACCOUNT,
    )


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
    refresh_tokens: RefreshTokenRepository
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
        verification_url = (
            f"{self.settings.public_base_url}{API_PREFIX}/auth/verify?token={raw_token}"
        )
        await self.email_sender.send_verification(to=user.email, verification_url=verification_url)
        return raw_token

    async def verify_email(self, raw_token: str) -> User:
        now = datetime.now(UTC)
        token = await self.verification_tokens.find_by_hash(hash_token(raw_token))
        if token is not None and token.used_at is not None:
            # Mail clients open a link more than once; a link that already
            # verified its account answers as it did the first time.
            user = await self.users.get(token.user_id)
            if user.is_email_verified:
                return user
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

    async def login(self, *, identifier: str, password: str) -> IssuedSession:
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
        deny_blocked_account(user, title="No se pudo iniciar sesión")

        if not user.is_email_verified:
            raise ProblemError(
                status=403,
                code="account-not-verified",
                title="No se pudo iniciar sesión",
                detail=UNVERIFIED_ACCOUNT,
            )

        self.deny_expired_temporary_password(user)

        await self.rate_limiter.reset(policy.key(identifier))
        access_token, expires_in = self.issue_session(user)
        # Every login starts a family of its own: the sessions of two devices
        # are separate chains, and closing one leaves the other open.
        refresh_token = await self.issue_refresh_token(
            user, family_id=uuid.uuid4(), now=datetime.now(UTC)
        )
        return IssuedSession(
            access_token=access_token, refresh_token=refresh_token, expires_in=expires_in
        )

    async def admin_login(self, *, email: str, password: str) -> tuple[str, int, bool]:
        """The backoffice door: same credentials, stricter policy, role required.

        Administrators are created by a superadmin or seeded, never
        self-registered, so there is no email verification to check here.

        The third value says whether the panel has to send the administrator
        straight to the password screen. The session is handed out either way:
        it is the only way to reach the endpoint that changes the password.
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

        deny_blocked_account(user, title="No se pudo iniciar sesión")

        self.deny_expired_temporary_password(user)

        await self.rate_limiter.reset(policy.key(email))
        token, expires_in = self.issue_session(user)
        return token, expires_in, user.must_change_password

    def deny_expired_temporary_password(
        self, user: User, *, title: str = "No se pudo iniciar sesión"
    ) -> None:
        """Checked at both doors, so an expired credential opens neither.

        Letting it through the app login would be enough to reach the change
        password endpoint and turn an expired credential into a permanent one.
        Refreshing a session asks again, with its own title.
        """
        if user.temporary_password_expired(datetime.now(UTC)):
            raise ProblemError(
                status=403,
                code="temporary-password-expired",
                title=title,
                detail=EXPIRED_TEMPORARY_PASSWORD,
            )

    def issue_session(self, user: User) -> tuple[str, int]:
        token = issue_access_token(
            self.signing_key,
            subject=user.id,
            role=user.role.value,
            handle=user.handle,
            profile_visibility=user.profile_visibility.value,
            expires_in_minutes=self.settings.access_token_minutes,
            issuer=self.settings.jwt_issuer,
        )
        return token, self.settings.access_token_minutes * 60

    async def issue_refresh_token(self, user: User, *, family_id: uuid.UUID, now: datetime) -> str:
        """Hand out the next token of a family. Only its digest is stored."""
        raw_token = generate_refresh_token()
        await self.refresh_tokens.add(
            RefreshToken(
                user_id=user.id,
                family_id=family_id,
                token_hash=hash_token(raw_token),
                expires_at=now + timedelta(days=self.settings.refresh_token_days),
            )
        )
        return raw_token

    async def refresh(self, raw_token: str) -> IssuedSession:
        """Trade a refresh token for a new access token and the next refresh token.

        Every token works once. Presenting one again means somebody kept a copy,
        and there is no telling the thief from the owner, so the whole account
        is signed out and has to log in again.
        """
        now = datetime.now(UTC)
        token_hash = hash_token(raw_token)

        consumed = await self.refresh_tokens.consume(token_hash, now=now)
        if consumed is None:
            await self.refuse_refresh_token(token_hash, now=now)

        user = await self.users.get(consumed.user_id)
        if user is None:
            raise InvalidRefreshTokenError()

        # The state of the account is read on every refresh and not only at
        # login: a suspension or a review has to stop a session that is already
        # open, and the access token alone only covers fifteen minutes of it.
        # These raise, which rolls back the consumption: the token stays usable
        # for whoever the account is released to.
        deny_blocked_account(user, title=REFRESH_FAILED_TITLE)
        self.deny_expired_temporary_password(user, title=REFRESH_FAILED_TITLE)

        access_token, expires_in = self.issue_session(user)
        refresh_token = await self.issue_refresh_token(user, family_id=consumed.family_id, now=now)
        return IssuedSession(
            access_token=access_token, refresh_token=refresh_token, expires_in=expires_in
        )

    async def refuse_refresh_token(self, token_hash: str, *, now: datetime) -> NoReturn:
        """Always raises: either the token is no good, or it was used a second time.

        A token already used and not yet revoked is the signal. One whose family
        was revoked, by a logout or by an earlier detection, already ended what
        it could open, so presenting it again is only an invalid token: acting
        on it too would let whoever holds an old copy sign the owner out again
        and again.
        """
        token = await self.refresh_tokens.find_by_hash(token_hash)
        if token is not None and token.used_at is not None and token.revoked_at is None:
            await self.refresh_tokens.revoke_all(token.user_id, revoked_at=now)
            # The access tokens already handed out are still good for fifteen
            # minutes, and the thief may hold one.
            await self.sessions.revoke_all(
                token.user_id,
                now=now,
                ttl_seconds=self.settings.access_token_minutes * 60,
            )
            raise ReusedRefreshTokenError()
        raise InvalidRefreshTokenError()

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

    async def logout(self, token: str, refresh_token: str | None = None) -> None:
        """Revoke the token that was used to call this, and the refresh token's family.

        A JWT is self-contained and the server never stored it, so logging out
        means recording its jti as revoked until it would have expired anyway.

        The refresh token is what keeps a session alive after that, so the app
        sends it along. One that is unknown, or belongs to somebody else, is
        ignored: logging out has nothing to refuse.
        """
        try:
            claims = decode_access_token(
                self.signing_key.public_key(),
                token,
                issuer=self.settings.jwt_issuer,
            )
        except jwt.ExpiredSignatureError:
            # Already unusable on its own; revoking it changes nothing, so this
            # is not an error. Logout is idempotent. The refresh token is the
            # one that can still open a session, and an expired token says
            # nothing about who is calling, so holding the refresh token is the
            # proof of ownership.
            await self.revoke_refresh_family(refresh_token, owner=None)
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
        await self.revoke_refresh_family(refresh_token, owner=uuid.UUID(claims["sub"]))

    async def revoke_refresh_family(
        self, raw_token: str | None, *, owner: uuid.UUID | None
    ) -> None:
        """End the chain a refresh token belongs to, when there is one to end.

        With an owner, the token has to be theirs: the access token proves who
        is calling, and logging out must not close somebody else's session.
        """
        if raw_token is None:
            return
        token = await self.refresh_tokens.find_by_hash(hash_token(raw_token))
        if token is None or (owner is not None and token.user_id != owner):
            return
        await self.refresh_tokens.revoke_family(token.family_id, revoked_at=datetime.now(UTC))
