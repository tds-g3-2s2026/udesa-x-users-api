"""Where the interfaces get their implementations.

This is the seam. Above it the services talk to the abstractions in
`core/ports.py` and in each feature's `repositories.py`; below it live the
classes under `infrastructure/`. Moving a piece to another technology is
changing what this module hands out, and nothing else.

The connections themselves are opened once in the lifespan and read from
`app.state`, so a feature never reaches in there by hand.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from users_api.app.clients.email import EmailSender
from users_api.app.repositories.rate_limiter import RateLimiter
from users_api.app.repositories.sessions import SessionStore
from users_api.app.repositories.tokens import (
    EmailVerificationTokenRepository,
    PasswordResetTokenRepository,
)
from users_api.app.repositories.users import UserRepository
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
