"""Where the interfaces get their implementations.

This is the seam. Above it the services talk to the abstractions in
`core/ports.py` and in each feature's `repositories.py`; below it live the
classes under `infrastructure/`. Moving a piece to another technology is
changing what this module hands out, and nothing else.

The connections themselves are opened once in the lifespan and read from
`app.state`, so a feature never reaches in there by hand.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from users_api.app.clients.email import EmailSender
from users_api.app.errors import ProblemError
from users_api.app.models.user import User
from users_api.app.repositories.rate_limiter import RateLimiter
from users_api.app.repositories.sessions import SessionStore
from users_api.app.repositories.tokens import (
    EmailVerificationTokenRepository,
    PasswordResetTokenRepository,
)
from users_api.app.repositories.users import UserRepository
from users_api.app.security import decode_access_token
from users_api.config.settings import Settings
from users_api.infrastructure.database.email_verification_token_repository import (
    SqlAlchemyEmailVerificationTokenRepository,
)
from users_api.infrastructure.database.password_reset_token_repository import (
    SqlAlchemyPasswordResetTokenRepository,
)
from users_api.infrastructure.database.session import session_scope
from users_api.infrastructure.database.user_repository import SqlAlchemyUserRepository
from users_api.infrastructure.redis.rate_limiter import RedisRateLimiter
from users_api.infrastructure.redis.session_store import RedisSessionStore


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """A transaction per request, committed when the handler returns."""
    async for session in session_scope(request.app.state.session_factory):
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_signing_key(request: Request) -> object:
    return request.app.state.signing_key


def get_email_sender(request: Request) -> EmailSender:
    return request.app.state.email_sender


def get_rate_limiter(request: Request) -> RateLimiter:
    return RedisRateLimiter(redis=request.app.state.redis)


def get_session_store(request: Request) -> SessionStore:
    return RedisSessionStore(redis=request.app.state.redis)


def get_user_repository(session: SessionDep) -> UserRepository:
    return SqlAlchemyUserRepository(session=session)


def get_verification_token_repository(session: SessionDep) -> EmailVerificationTokenRepository:
    return SqlAlchemyEmailVerificationTokenRepository(session=session)


def get_reset_token_repository(session: SessionDep) -> PasswordResetTokenRepository:
    return SqlAlchemyPasswordResetTokenRepository(session=session)


SettingsDep = Annotated[Settings, Depends(get_settings)]
SigningKeyDep = Annotated[object, Depends(get_signing_key)]
EmailSenderDep = Annotated[EmailSender, Depends(get_email_sender)]
RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]
SessionStoreDep = Annotated[SessionStore, Depends(get_session_store)]
UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]
VerificationTokenRepositoryDep = Annotated[
    EmailVerificationTokenRepository, Depends(get_verification_token_repository)
]
ResetTokenRepositoryDep = Annotated[
    PasswordResetTokenRepository, Depends(get_reset_token_repository)
]


# Rejects a missing or malformed Authorization header before anything else runs.
bearer_scheme = HTTPBearer()
BearerDep = Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)]


async def get_current_user(
    credentials: BearerDep,
    users: UserRepositoryDep,
    sessions: SessionStoreDep,
    signing_key: SigningKeyDep,
) -> User:
    """The account behind the bearer token, or no answer at all.

    This is the other half of the revocation that logging out and resetting a
    password write down. Signing the token is not enough to trust it: a token
    that was revoked before its own expiry has to be refused here, or closing a
    session would be a promise the service does not keep.
    """
    try:
        claims = decode_access_token(signing_key.public_key(), credentials.credentials)
    except jwt.InvalidTokenError as exc:
        raise ProblemError(
            status=401,
            code="invalid-token",
            title="No se pudo autenticar la solicitud",
            detail="El token no es válido",
        ) from exc

    user_id = uuid.UUID(claims["sub"])
    issued_at = datetime.fromtimestamp(claims["iat"], tz=UTC)
    cutoff = await sessions.revoked_before(user_id)

    # Compared with <= and not <: the cutoff is stored truncated to the second,
    # so a token issued inside that same second would otherwise survive the very
    # change of password that was supposed to kill it.
    revoked = await sessions.is_token_revoked(claims["jti"]) or (
        cutoff is not None and issued_at <= cutoff
    )
    if revoked:
        raise ProblemError(
            status=401,
            code="session-revoked",
            title="La sesión ya no es válida",
            detail="Tu sesión se cerró. Iniciá sesión de nuevo",
        )

    user = await users.get(user_id)
    if user is None or not user.can_log_in:
        # A token outlives a suspension, so the state of the account is checked
        # on every request and not only when it is handed out.
        raise ProblemError(
            status=403,
            code="account-suspended",
            title="No se pudo autenticar la solicitud",
            detail="Cuenta suspendida",
        )
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]
