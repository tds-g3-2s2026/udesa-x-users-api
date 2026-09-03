import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from users_api.core.config import get_settings
from users_api.core.db import build_session_factory
from users_api.core.errors import (
    ProblemError,
    problem_error_handler,
    validation_error_handler,
)
from users_api.core.security import load_signing_key
from users_api.features.auth.router import router as auth_router
from users_api.features.health.router import router as health_router
from users_api.features.password_reset.router import router as password_reset_router
from users_api.infrastructure.email.console import ConsoleEmailSender


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Connections are opened once and shared. Creating an engine per request
    # exhausts the PostgreSQL pool as soon as there is any load.
    settings = get_settings()

    # Uvicorn only configures its own loggers and leaves the root at WARNING, so
    # without this every logger.info in the service is dropped, including the
    # links written by the email adapter.
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
        force=True,
    )

    app.state.settings = settings
    app.state.engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    app.state.session_factory = build_session_factory(app.state.engine)
    app.state.redis = Redis.from_url(settings.redis_url)
    app.state.signing_key = load_signing_key(settings.jwt_private_key)
    app.state.email_sender = ConsoleEmailSender()
    yield
    await app.state.engine.dispose()
    await app.state.redis.aclose()


app = FastAPI(title="UdeSA-X Users API", version="0.1.0", lifespan=lifespan)

app.add_exception_handler(ProblemError, problem_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(password_reset_router)
