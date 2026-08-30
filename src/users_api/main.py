import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from users_api.auth_router import router as auth_router
from users_api.config import get_settings
from users_api.db import build_session_factory
from users_api.email import ConsoleEmailSender
from users_api.errors import (
    ProblemError,
    problem_error_handler,
    validation_error_handler,
)
from users_api.health import build_report, check_postgres, check_redis
from users_api.security import load_signing_key


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Connections are opened once and shared. Creating an engine per request
    # exhausts the PostgreSQL pool as soon as there is any load.
    settings = get_settings()

    # Uvicorn only configures its own loggers and leaves the root at WARNING, so
    # without this every logger.info in the service is dropped, including the
    # verification link written by the email adapter.
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

app.include_router(auth_router)


@app.get("/healthcheck", tags=["health"])
async def healthcheck() -> JSONResponse:
    """Check PostgreSQL and Redis before reporting the service as healthy."""
    statuses = [
        await check_postgres(app.state.engine),
        await check_redis(app.state.redis),
    ]
    body, status_code = build_report(statuses)
    return JSONResponse(body, status_code=status_code)
