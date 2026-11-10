"""The last successful login of an account (E5-H9)."""

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from tests.integration.helpers import set_user_flag
from users_api.infrastructure.database.models import UserModel

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL"),
    reason="requires DATABASE_URL and REDIS_URL pointing at real services",
)


async def last_login_at(api) -> datetime | None:
    """The column as stored. The suite registers a single account per test."""
    async with api.app.state.engine.connect() as connection:
        return await connection.scalar(select(UserModel.last_login_at))


async def test_e5_h9_ca1_a_successful_login_updates_last_login_at(api):
    await api.register_and_verify()
    assert await last_login_at(api) is None
    before = datetime.now(UTC)

    response = await api.login()

    assert response.status_code == 200
    assert await last_login_at(api) >= before


async def test_e5_h9_ca1_a_failed_login_leaves_it_as_it_was(api):
    await api.register_and_verify()
    await api.login()
    recorded = await last_login_at(api)

    response = await api.login(password="Incorrecta1")

    assert response.status_code == 401
    assert await last_login_at(api) == recorded


async def test_an_account_refused_after_its_password_records_nothing(api):
    await api.register_and_verify()
    await set_user_flag(api.app, "status", "suspended")

    response = await api.login()

    # The password was right, but the login was not successful.
    assert response.status_code == 403
    assert await last_login_at(api) is None


async def test_a_refreshed_session_does_not_move_it(api):
    await api.register_and_verify()
    session = (await api.login()).json()
    recorded = await last_login_at(api)

    response = await api.refresh(session["refresh_token"])

    assert response.status_code == 200
    assert await last_login_at(api) == recorded


async def test_logging_into_the_backoffice_records_it_too(api):
    await api.register_and_verify()
    await set_user_flag(api.app, "role", "moderator")
    before = datetime.now(UTC)

    response = await api.admin_login()

    assert response.status_code == 200
    assert await last_login_at(api) >= before
