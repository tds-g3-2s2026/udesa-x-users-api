import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from users_api.api.admin_auth import router as admin_auth_router
from users_api.api.admin_users import router as admin_users_router
from users_api.api.auth import router as auth_router
from users_api.api.errors import (
    problem_error_handler,
    validation_error_handler,
)
from users_api.api.health import router as health_router
from users_api.api.password_change import router as password_change_router
from users_api.api.password_reset import router as password_reset_router
from users_api.api.preferences import router as preferences_router
from users_api.api.profile import router as profile_router
from users_api.app.errors import ProblemError
from users_api.app.security import load_signing_key
from users_api.config.settings import API_PREFIX, get_settings
from users_api.infrastructure.database.session import build_session_factory
from users_api.infrastructure.email.console import ConsoleEmailSender
from users_api.infrastructure.email.resend import ResendEmailSender


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
    if settings.email_provider == "resend":
        app.state.email_sender = ResendEmailSender(
            api_key=settings.resend_api_key, sender=settings.email_from
        )
    else:
        app.state.email_sender = ConsoleEmailSender()
    yield
    await app.state.engine.dispose()
    await app.state.redis.aclose()


app = FastAPI(title="UdeSA-X Users API", version="0.1.0", lifespan=lifespan)

# Middleware has to be in place before the first request builds the stack, so
# the origins are read here and not in the lifespan. Only the backoffice runs in
# a browser; with the list empty no browser origin gets through.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allowed_origins,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
    # The lockout answer carries how long to wait; without this the browser
    # hides the header from the page.
    expose_headers=["Retry-After"],
)

app.add_exception_handler(ProblemError, problem_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)

# The healthcheck stays out: the Kubernetes probes reach the pod directly and
# never pass through the Ingress.
app.include_router(health_router)

app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(admin_auth_router, prefix=API_PREFIX)
app.include_router(admin_users_router, prefix=API_PREFIX)
app.include_router(password_reset_router, prefix=API_PREFIX)
app.include_router(password_change_router, prefix=API_PREFIX)
app.include_router(profile_router, prefix=API_PREFIX)
app.include_router(preferences_router, prefix=API_PREFIX)
