"""E5-H1: creating administrators from the panel."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

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


async def test_e5_h1_ca1_temporary_password_forces_change_on_first_login(api):
    creator = await sign_in_as(api, "superadmin")
    temporary_password = (await api.create_administrator(creator)).json()["temporary_password"]
    chosen_password = "Elegida2026"

    first = await api.admin_login(email=NEW_ADMINISTRATOR["email"], password=temporary_password)
    assert first.status_code == 200
    assert first.json()["must_change_password"] is True

    # The session exists, and it only opens one door.
    token = first.json()["access_token"]
    blocked = await api.get_profile(token)
    assert blocked.status_code == 403
    assert blocked.json()["type"].endswith("password-change-required")

    changed = await api.change_password(token, current=temporary_password, new=chosen_password)
    assert changed.status_code == 200

    # Changing the password revokes every session with a cutoff truncated to
    # the second (deps.py), so a token minted inside that same second would be
    # born revoked. Somebody retyping their credentials always takes longer.
    await asyncio.sleep(1)

    # The obligation is gone, and so is the temporary password.
    assert (
        await api.admin_login(email=NEW_ADMINISTRATOR["email"], password=temporary_password)
    ).status_code == 401
    second = await api.admin_login(email=NEW_ADMINISTRATOR["email"], password=chosen_password)
    assert second.json()["must_change_password"] is False
    assert (await api.get_profile(second.json()["access_token"])).status_code == 200


async def test_e5_h1_ca3_temporary_password_expires_after_24_hours(api):
    creator = await sign_in_as(api, "superadmin")
    temporary_password = (await api.create_administrator(creator)).json()["temporary_password"]

    # A day later, without anybody having used it.
    await set_user_flag(
        api.app, "temporary_password_expires_at", datetime.now(UTC) - timedelta(minutes=1)
    )

    expired = await api.admin_login(email=NEW_ADMINISTRATOR["email"], password=temporary_password)
    assert expired.status_code == 403
    assert expired.json()["type"].endswith("temporary-password-expired")

    # The app door does not let it through either, which would otherwise be a
    # way to reach the change password endpoint with a dead credential.
    through_the_app = await api.login(
        identifier=NEW_ADMINISTRATOR["email"], password=temporary_password
    )
    assert through_the_app.status_code == 403
