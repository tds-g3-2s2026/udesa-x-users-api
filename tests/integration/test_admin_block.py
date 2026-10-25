"""An administrator blocking an app account with a reason (E5-H5)."""

import logging
import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import update

from users_api.api import admin_user_accounts
from users_api.infrastructure.database.models import UserModel

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL"),
    reason="requires DATABASE_URL and REDIS_URL pointing at real services",
)

MODERATOR = {"email": "moderadora@udesa.edu.ar", "handle": "@moderadora"}
SUPERADMIN = {"email": "jefa@udesa.edu.ar", "handle": "@jefa_admin"}
OTHER_USER = {"email": "otra@udesa.edu.ar", "handle": "@otra_cuenta"}
REASON = "Publica spam en las respuestas de otros usuarios"


async def given_registered(api, **overrides) -> str:
    user_id = (await api.register(**overrides)).json()["id"]
    await api.verify_last()
    return user_id


async def set_columns(api, user_id: str, **values) -> None:
    """Change one account straight in the table; `set_user_flag` changes them all."""
    async with api.app.state.engine.begin() as connection:
        await connection.execute(
            update(UserModel).where(UserModel.id == uuid.UUID(user_id)).values(**values)
        )


async def administrator_with_id(api, account: dict[str, str], role: str):
    """A registered account, promoted, with its id and the headers of its backoffice session."""
    user_id = await given_registered(api, **account)
    await set_columns(api, user_id, role=role)
    token = (await api.admin_login(account["email"])).json()["access_token"]
    return user_id, {"Authorization": f"Bearer {token}"}


async def administrator(api, account: dict[str, str], role: str) -> dict[str, str]:
    return (await administrator_with_id(api, account, role))[1]


async def block(api, headers: dict[str, str], user_id: str, body: dict | None = None):
    return await api.client.post(
        f"/admin/users/{user_id}/block",
        headers=headers,
        json={"reason": REASON} if body is None else body,
    )


async def detail(api, headers: dict[str, str], user_id: str) -> dict:
    return (await api.client.get(f"/admin/users/{user_id}", headers=headers)).json()


async def test_e5_h5_ca1_blocking_without_a_reason_is_refused(api):
    headers = await administrator(api, MODERATOR, "moderator")
    user_id = await given_registered(api)

    response = await block(api, headers, user_id, body={})

    assert response.status_code == 422
    body = response.json()
    assert body["type"].endswith("/validation-failed")
    assert [error["field"] for error in body["errors"]] == ["reason"]
    # Nothing happened: the account still gets in.
    assert (await api.login()).status_code == 200


async def test_e5_h5_ca1_a_blank_reason_counts_as_missing(api):
    headers = await administrator(api, MODERATOR, "moderator")
    user_id = await given_registered(api)

    response = await block(api, headers, user_id, body={"reason": "   \n\t "})

    assert response.status_code == 422
    body = response.json()
    assert body["type"].endswith("/validation-failed")
    assert [error["field"] for error in body["errors"]] == ["reason"]
    assert (await detail(api, headers, user_id))["status"] == "active"


async def test_e5_h5_ca1_a_reason_over_500_characters_is_refused(api):
    headers = await administrator(api, MODERATOR, "moderator")
    user_id = await given_registered(api)

    too_long = await block(api, headers, user_id, body={"reason": "x" * 501})
    # The spaces around do not count against the limit.
    just_fits = await block(api, headers, user_id, body={"reason": f"  {'x' * 500}  "})

    assert too_long.status_code == 422
    assert just_fits.status_code == 204
    assert (await detail(api, headers, user_id))["status_reason"] == "x" * 500


async def test_e5_h5_ca2_blocked_user_loses_access_at_once(api):
    headers = await administrator(api, MODERATOR, "moderator")
    user_id = await given_registered(api)
    phone = (await api.login()).json()["access_token"]
    laptop = (await api.login()).json()["access_token"]

    assert (await block(api, headers, user_id)).status_code == 204

    for token in (phone, laptop):
        refused = await api.get_profile(token)
        assert refused.status_code == 401
        assert refused.json()["type"].endswith("/session-revoked")
    login = await api.login()
    assert login.status_code == 403
    assert login.json()["type"].endswith("/account-suspended")
    # The reason is a sanction: the owner gets the generic message, not it.
    assert login.json()["detail"] == "Cuenta suspendida"


async def test_e5_h5_ca2_the_refresh_token_stops_working(api):
    headers = await administrator(api, MODERATOR, "moderator")
    user_id = await given_registered(api)
    session = (await api.login()).json()

    assert (await block(api, headers, user_id)).status_code == 204

    # Even once the Redis cutoff is gone, as after its fifteen minutes: the
    # refresh token itself was revoked.
    await api.app.state.redis.flushdb()
    refused = await api.refresh(session["refresh_token"])
    assert refused.status_code == 401
    assert refused.json()["type"].endswith("/invalid-refresh-token")


async def test_e5_h5_ca2_blocking_twice_keeps_the_first_reason(api):
    first = await administrator(api, MODERATOR, "moderator")
    second = await administrator(api, SUPERADMIN, "superadmin")
    user_id = await given_registered(api)
    assert (await block(api, first, user_id)).status_code == 204
    blocked = await detail(api, first, user_id)

    again = await block(api, second, user_id, body={"reason": "Otro motivo"})

    assert again.status_code == 204
    assert await detail(api, first, user_id) == blocked
    assert blocked["status_reason"] == REASON


async def test_e5_h5_administrators_cannot_be_blocked(api):
    headers = await administrator(api, MODERATOR, "moderator")
    superadmin_id = await given_registered(api, **SUPERADMIN)
    await set_columns(api, superadmin_id, role="superadmin")

    response = await block(api, headers, superadmin_id)

    assert response.status_code == 422
    assert response.json()["type"].endswith("/administrator-cannot-be-blocked")
    assert (await api.admin_login(SUPERADMIN["email"])).status_code == 200


async def test_e5_h5_the_detail_shows_the_reason_and_when(api):
    headers = await administrator(api, MODERATOR, "moderator")
    user_id = await given_registered(api)
    before = datetime.now(UTC)

    await block(api, headers, user_id, body={"reason": f"  {REASON}  "})

    body = await detail(api, headers, user_id)
    assert body["status"] == "suspended"
    assert body["status_reason"] == REASON
    assert datetime.fromisoformat(body["status_changed_at"]) >= before


async def test_e5_h5_an_account_under_review_is_blocked_with_the_administrator_reason(api):
    headers = await administrator(api, MODERATOR, "moderator")
    user_id = await given_registered(api)
    await set_columns(api, user_id, status="under_review")

    assert (await block(api, headers, user_id)).status_code == 204

    body = await detail(api, headers, user_id)
    assert (body["status"], body["status_reason"]) == ("suspended", REASON)


@pytest.mark.parametrize("deleted", [False, True])
async def test_e5_h5_an_unknown_or_deleted_account_is_not_found(api, deleted):
    headers = await administrator(api, MODERATOR, "moderator")
    user_id = str(uuid.uuid4())
    if deleted:
        user_id = await given_registered(api)
        await set_columns(api, user_id, deleted_at=datetime.now(UTC))

    response = await block(api, headers, user_id)

    assert response.status_code == 404
    assert response.json()["type"].endswith("/account-not-found")


async def test_e5_h5_an_app_user_cannot_block(api):
    target_id = await given_registered(api, **OTHER_USER)
    await given_registered(api)
    token = (await api.login()).json()["access_token"]

    response = await block(api, {"Authorization": f"Bearer {token}"}, target_id)

    assert response.status_code == 403
    assert response.json()["type"].endswith("/administrator-required")


async def test_e5_h5_blocking_leaves_an_audit_entry(api, caplog):
    moderator_id, headers = await administrator_with_id(api, MODERATOR, "moderator")
    user_id = await given_registered(api)

    with caplog.at_level(logging.INFO, logger="users_api.app.services.account_block"):
        await block(api, headers, user_id)

    # The log is shared by the whole process: the entry is found by its target.
    [entry] = [
        one for one in admin_user_accounts.audit_log.entries if one.target_id == uuid.UUID(user_id)
    ]
    assert entry.actor_id == uuid.UUID(moderator_id)
    assert (entry.action, entry.target_type) == ("user.blocked", "user")
    assert entry.details == {"reason": REASON}
    # Only the ids reach the log that leaves the pod, never the reason.
    [line] = [
        record.getMessage()
        for record in caplog.records
        if record.name == "users_api.app.services.account_block"
    ]
    assert user_id in line
    assert moderator_id in line
    assert REASON not in line
