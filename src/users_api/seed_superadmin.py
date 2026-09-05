"""Seed the first superadmin: `python -m users_api.seed_superadmin`.

The panel cannot create the first administrator because nobody can log into
the panel yet. This runs before the API starts, reads the address and password
from the environment, and does nothing when the account already exists, so it
is safe to run on every deploy.

An entrypoint like `main.py`: it wires the concrete pieces itself and is the
only reason the business rule in `AdminService` ever sees a real database.
"""

import asyncio
import logging
import sys

from sqlalchemy.ext.asyncio import create_async_engine

from users_api.api.schemas.auth import PASSWORD_MIN_LENGTH, enforce_password_policy
from users_api.app.services.admins import AdminService
from users_api.config.settings import Settings, get_settings
from users_api.infrastructure.database.session import build_session_factory, session_scope
from users_api.infrastructure.database.user_repository import SqlAlchemyUserRepository

logger = logging.getLogger(__name__)


class SeedConfigurationError(ValueError):
    """The environment does not describe a valid superadmin."""


def validate(settings: Settings) -> tuple[str, str, str]:
    if not settings.superadmin_email or not settings.superadmin_password:
        raise SeedConfigurationError(
            "SUPERADMIN_EMAIL and SUPERADMIN_PASSWORD must both be set to seed the superadmin"
        )
    password = settings.superadmin_password
    if len(password) < PASSWORD_MIN_LENGTH:
        raise SeedConfigurationError(
            f"SUPERADMIN_PASSWORD must have at least {PASSWORD_MIN_LENGTH} characters"
        )
    try:
        # The same policy registration enforces. A weaker password for the most
        # privileged account would be backwards.
        enforce_password_policy(password)
    except ValueError as exc:
        raise SeedConfigurationError(f"SUPERADMIN_PASSWORD: {exc}") from exc
    return settings.superadmin_email, settings.superadmin_handle, password


async def run(settings: Settings) -> bool:
    """Create the superadmin if missing. Returns whether it was created."""
    email, handle, password = validate(settings)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async for session in session_scope(build_session_factory(engine)):
            service = AdminService(users=SqlAlchemyUserRepository(session=session))
            created = await service.ensure_superadmin(email=email, handle=handle, password=password)
    finally:
        await engine.dispose()

    if created is None:
        logger.info("Superadmin %s already exists, nothing to do", email.strip().lower())
        return False
    logger.info("Superadmin %s created", created.email)
    return True


def main() -> int:
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)-8s %(name)s | %(message)s")
    try:
        asyncio.run(run(get_settings()))
    except SeedConfigurationError as exc:
        logger.error("%s", exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
