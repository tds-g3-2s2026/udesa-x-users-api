import os

import pytest

# Integration tests need PostgreSQL and Redis. docker/docker-compose.dev.yml
# provides both; without the variables the whole integration suite is skipped so
# the unit tests still run on any machine.
HAS_SERVICES = bool(os.getenv("DATABASE_URL") and os.getenv("REDIS_URL"))


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session", autouse=True)
def apply_migrations() -> None:
    """Bring the schema up with Alembic, not with metadata.create_all.

    Running the real migration means the tests also prove that it matches the
    models: a column added to a model without its migration fails here instead
    of in production.
    """
    if not HAS_SERVICES:
        return

    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")


@pytest.fixture
async def clean_state():
    """Empty the tables and the lockout counters between tests."""
    if not HAS_SERVICES:
        yield
        return

    from redis.asyncio import Redis
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(os.environ["DATABASE_URL"])
    redis = Redis.from_url(os.environ["REDIS_URL"])
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE users, email_verification_tokens CASCADE"))
    await redis.flushdb()

    yield

    await engine.dispose()
    await redis.aclose()
