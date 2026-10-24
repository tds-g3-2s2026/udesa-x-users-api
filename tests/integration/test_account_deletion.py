"""Closing one's own account by proving knowledge of the current password.

The account is marked, not removed: other tables point at the row. What these
tests pin down is what the owner and everybody else can still do afterwards.
"""

import os

import pytest
from sqlalchemy import text

from tests.integration.helpers import REGISTRATION, set_user_flag

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL"),
    reason="requires DATABASE_URL and REDIS_URL pointing at real services",
)

CURRENT_PASSWORD = REGISTRATION["password"]
NEW_PASSWORD = "Contrasena2"


async def open_session(api) -> dict:
    """A usable account and the whole login answer, refresh token included."""
    await api.register_and_verify()
    return (await api.login()).json()


async def account_row(api):
    async with api.app.state.engine.begin() as connection:
        result = await connection.execute(
            text("SELECT deleted_at FROM users WHERE email = :email"),
            {"email": REGISTRATION["email"].lower()},
        )
        return result.first()


async def test_e1_h4_ca1_soft_delete_keeps_row_and_blocks_login(api):
    session = await open_session(api)
    other_device = (await api.login()).json()

    response = await api.delete_account(session["access_token"], CURRENT_PASSWORD)
    assert response.status_code == 200
    assert response.json() == {"status": "deleted"}

    # The row is still there, only marked.
    row = await account_row(api)
    assert row is not None
    assert row.deleted_at is not None

    # Signing in is refused with the words a suspended account gets, once the
    # password has proved the caller owns it.
    login = await api.login()
    assert login.status_code == 403
    assert login.json()["type"].endswith("/account-suspended")

    # Every session is gone, the one that made the call and the other device.
    for token in (session["access_token"], other_device["access_token"]):
        revoked = await api.get_profile(token)
        assert revoked.status_code == 401
        assert revoked.json()["type"].endswith("/session-revoked")

    # And so are the refresh tokens, so no new access token can be minted.
    refreshed = await api.refresh(session["refresh_token"])
    assert refreshed.status_code == 401
    assert refreshed.json()["type"].endswith("/invalid-refresh-token")


async def test_e1_h4_ca3_wrong_password_does_not_delete(api):
    session = await open_session(api)

    response = await api.delete_account(session["access_token"], "Incorrecta1")
    assert response.status_code == 400
    assert response.json()["type"].endswith("/invalid-current-password")

    assert (await account_row(api)).deleted_at is None
    # Nothing was revoked: the session still works and so does signing in.
    assert (await api.get_profile(session["access_token"])).status_code == 200
    assert (await api.login()).status_code == 200


async def test_a_missing_password_is_a_validation_error_on_that_field(api):
    session = await open_session(api)

    response = await api.client.request(
        "DELETE",
        "/me",
        headers={"Authorization": f"Bearer {session['access_token']}"},
        json={},
    )
    assert response.status_code == 422
    assert [problem["field"] for problem in response.json()["errors"]] == ["current_password"]
    assert (await account_row(api)).deleted_at is None


async def test_deleting_and_changing_the_password_share_one_attempt_budget(api):
    session = await open_session(api)
    token = session["access_token"]

    # Two wrong attempts at one operation, a third at the other: the budget of
    # three is spent across both, not three each.
    for _ in range(2):
        assert (await api.change_password(token, "Incorrecta1", NEW_PASSWORD)).status_code == 400
    assert (await api.delete_account(token, "Incorrecta1")).status_code == 400

    blocked = await api.delete_account(token, CURRENT_PASSWORD)
    assert blocked.status_code == 429
    assert blocked.json()["type"].endswith("/too-many-password-attempts")
    assert blocked.headers["Retry-After"] == str(15 * 60)
    # The other operation is shut as well, even with the right password.
    assert (await api.change_password(token, CURRENT_PASSWORD, NEW_PASSWORD)).status_code == 429

    # Only these operations are shut: nothing was deleted and signing in works.
    assert (await account_row(api)).deleted_at is None
    assert (await api.login()).status_code == 200


@pytest.mark.parametrize(
    ("status", "code"),
    [("suspended", "account-suspended"), ("under_review", "account-under-review")],
)
async def test_a_blocked_account_cannot_delete_itself(api, status, code):
    session = await open_session(api)
    await set_user_flag(api.app, "status", status)

    response = await api.delete_account(session["access_token"], CURRENT_PASSWORD)
    assert response.status_code == 403
    assert response.json()["type"].endswith(f"/{code}")
    assert (await account_row(api)).deleted_at is None


@pytest.mark.parametrize("role", ["moderator", "superadmin"])
async def test_an_administrator_cannot_delete_its_own_account(api, role):
    session = await open_session(api)
    await set_user_flag(api.app, "role", role)

    response = await api.delete_account(session["access_token"], CURRENT_PASSWORD)
    assert response.status_code == 403
    assert response.json()["type"].endswith("/administrator-cannot-delete-account")
    assert (await account_row(api)).deleted_at is None
    # The refusal did not touch the session.
    assert (await api.get_profile(session["access_token"])).status_code == 200


async def test_a_deleted_account_keeps_its_email_and_handle_reserved(api):
    session = await open_session(api)
    await api.delete_account(session["access_token"], CURRENT_PASSWORD)

    again = await api.register()
    assert again.status_code == 409
    assert again.json()["type"].endswith("/account-already-exists")
