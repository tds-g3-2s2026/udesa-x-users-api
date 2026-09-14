"""E5-H1: creating administrators from the panel."""

import os

import pytest

from tests.integration.helpers import NEW_ADMINISTRATOR, Api, set_user_flag

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL"),
    reason="requires DATABASE_URL and REDIS_URL pointing at real services",
)


async def sign_in_as(api: Api, role: str) -> str:
    """A verified app user promoted to `role`, signed into the backoffice.

    The first administrator of a real deployment comes from the seed; here the
    role is set by hand so each test starts from the door it needs.
    """
    await api.register_and_verify()
    await set_user_flag(api.app, "role", role)
    response = await api.admin_login()
    return response.json()["access_token"]


async def test_e5_h1_a_superadmin_creates_an_administrator_with_a_temporary_password(api):
    token = await sign_in_as(api, "superadmin")

    response = await api.create_administrator(token)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == NEW_ADMINISTRATOR["email"]
    assert body["role"] == "moderator"
    # The password is handed back once, and it is the one that works.
    signed_in = await api.admin_login(
        email=NEW_ADMINISTRATOR["email"], password=body["temporary_password"]
    )
    assert signed_in.status_code == 200


async def test_e5_h1_ca2_moderator_cannot_create_administrators(api):
    token = await sign_in_as(api, "moderator")

    response = await api.create_administrator(token)

    assert response.status_code == 403
    assert response.json()["type"].endswith("superadmin-required")


async def test_e5_h1_an_address_already_taken_is_refused(api):
    token = await sign_in_as(api, "superadmin")
    await api.create_administrator(token)

    repeated = await api.create_administrator(token, handle="@otra_admin")

    assert repeated.status_code == 409
