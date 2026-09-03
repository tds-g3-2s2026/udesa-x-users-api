import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# Importing the models is what registers the tables on Base.metadata, which is
# what autogenerate compares the database against. Every feature that owns a
# table has to be listed here, or autogenerate will propose dropping it.
from users_api.core.config import get_settings
from users_api.core.db import Base
from users_api.features.auth import models as auth_models  # noqa: F401
from users_api.features.password_reset import models as password_reset_models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """The URL comes from the environment, never from alembic.ini.

    Keeping it out of the file means no credentials are versioned and the same
    migration runs against development and production without edits.
    """
    return get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(get_url())
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
