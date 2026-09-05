import os

import jwt
import pytest
from sqlalchemy import text

from tests.integration.helpers import REGISTRATION, Api, set_user_flag
from users_api.config.settings import Settings
from users_api.seed_superadmin import run

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL"),
    reason="requires DATABASE_URL and REDIS_URL pointing at real services",
)

SUPERADMIN = {"email": "admin@udesa.edu.ar", "password": "Admin1234"}


def seed_settings(**overrides) -> Settings:
    defaults = {
        "database_url": os.environ["DATABASE_URL"],
        "redis_url": os.environ["REDIS_URL"],
        "superadmin_email": SUPERADMIN["email"],
        "superadmin_password": SUPERADMIN["password"],
    }
    return Settings(**{**defaults, **overrides})


async def promote(api: Api, role: str) -> None:
    """A verified app user, promoted straight in the database.

    Creating administrators through the API is E5-H1; until then the role is
    set by hand, which is also what the seed does underneath.
    """
    await api.register_and_verify()
    await set_user_flag(api.app, "role", role)


def decode(api: Api, token: str) -> dict:
    return jwt.decode(token, api.app.state.signing_key.public_key(), algorithms=["EdDSA"])


async def test_e5_h2_ca1_token_carries_the_administrator_role(api):
    await promote(api, "superadmin")

    response = await api.admin_login()
    assert response.status_code == 200
    assert decode(api, response.json()["access_token"])["role"] == "superadmin"


async def test_e5_h2_ca1_a_moderator_gets_its_own_role(api):
    await promote(api, "moderator")

    response = await api.admin_login()
    assert decode(api, response.json()["access_token"])["role"] == "moderator"


async def test_e5_h2_ca1_the_app_login_also_reports_the_real_role(api):
    await promote(api, "moderator")

    response = await api.login()
    assert response.status_code == 200
    assert decode(api, response.json()["access_token"])["role"] == "moderator"


async def test_e5_h2_ca2_regular_user_gets_403_on_the_backoffice_login(api):
    await api.register_and_verify()

    denied = await api.admin_login()
    assert denied.status_code == 403
    assert denied.headers["content-type"].startswith("application/problem+json")
    assert denied.json()["type"].endswith("/not-an-administrator")

    # The app door still opens: the account is fine, it just has no admin role.
    assert (await api.login()).status_code == 200


async def test_e5_h2_ca2_a_regular_user_with_the_right_password_is_not_counted_as_a_failure(api):
    await api.register_and_verify()

    for _ in range(3):
        assert (await api.admin_login()).status_code == 403

    # Still 403, not 429: three correct passwords are not a brute force attempt.
    assert (await api.admin_login()).status_code == 403


async def test_e5_h2_ca3_locks_the_admin_login_after_three_failed_attempts(api):
    await promote(api, "superadmin")

    for _ in range(3):
        assert (await api.admin_login(password="Incorrecta1")).status_code == 401

    locked = await api.admin_login()
    assert locked.status_code == 429
    assert locked.headers["Retry-After"] == str(30 * 60)
    assert "30 minutos" in locked.json()["detail"]


async def test_e5_h2_ca3_the_two_doors_keep_separate_counters(api):
    await promote(api, "superadmin")

    for _ in range(3):
        await api.admin_login(password="Incorrecta1")
    assert (await api.admin_login()).status_code == 429

    # Locked out of the backoffice, but the app counter never moved.
    assert (await api.login()).status_code == 200


async def test_e5_h2_ca3_a_successful_admin_login_clears_the_counter(api):
    await promote(api, "superadmin")

    for _ in range(2):
        await api.admin_login(password="Incorrecta1")
    assert (await api.admin_login()).status_code == 200

    for _ in range(2):
        assert (await api.admin_login(password="Incorrecta1")).status_code == 401


async def test_e5_h2_seed_creates_the_superadmin_once_and_it_can_log_in(api):
    assert await run(seed_settings()) is True
    assert await run(seed_settings()) is False

    async with api.app.state.engine.begin() as connection:
        rows = await connection.execute(
            text("SELECT role, is_email_verified FROM users WHERE email = :email"),
            {"email": SUPERADMIN["email"]},
        )
        assert rows.all() == [("superadmin", True)]

    response = await api.admin_login(**SUPERADMIN)
    assert response.status_code == 200
    assert decode(api, response.json()["access_token"])["role"] == "superadmin"


async def test_e5_h2_seed_never_touches_an_existing_account(api):
    await api.register_and_verify()

    # Same address as the registered user: the seed must not promote or reset it.
    assert await run(seed_settings(superadmin_email=REGISTRATION["email"])) is False
    assert (await api.admin_login()).status_code == 403
