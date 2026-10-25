"""An account under review, as posts-api leaves it after enough reports (E3-H5)."""

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from tests.integration.helpers import set_user_flag
from users_api.infrastructure.database.models import UserModel

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL") or not os.getenv("RABBITMQ_URL"),
    reason="requires DATABASE_URL, REDIS_URL and RABBITMQ_URL pointing at real services",
)

UNDER_REVIEW = (
    "Tu cuenta está en revisión por denuncias de otros usuarios. "
    "Mientras dure la revisión no podés iniciar sesión"
)


def internal_token() -> str:
    # Read and not hardcoded: CI sets its own value.
    return os.environ["INTERNAL_API_TOKEN"]


async def register_verified(api) -> str:
    user_id = (await api.register()).json()["id"]
    await api.verify_last()
    return user_id


async def stored_status(api, user_id: str):
    """The status of the account together with its reason and moment, as stored."""
    async with api.app.state.engine.connect() as connection:
        result = await connection.execute(
            select(UserModel.status, UserModel.status_reason, UserModel.status_changed_at).where(
                UserModel.id == uuid.UUID(user_id)
            )
        )
        return result.one()


async def test_e3_h5_ca4_review_revokes_every_active_token(api):
    user_id = await register_verified(api)
    phone = (await api.login()).json()["access_token"]
    laptop = (await api.login()).json()["access_token"]

    response = await api.put_under_review(user_id, internal_token())
    assert response.status_code == 204

    for token in (phone, laptop):
        refused = await api.get_profile(token)
        assert refused.status_code == 401
        assert refused.json()["type"].endswith("/session-revoked")


async def test_review_revokes_every_refresh_token(api):
    user_id = await register_verified(api)
    phone = (await api.login()).json()
    laptop = (await api.login()).json()

    assert (await api.put_under_review(user_id, internal_token())).status_code == 204

    # Released from review and without the Redis cutoff, as if its fifteen
    # minutes had passed: the refresh tokens are still dead.
    await set_user_flag(api.app, "status", "active")
    await api.app.state.redis.flushdb()
    for session in (phone, laptop):
        refused = await api.refresh(session["refresh_token"])
        assert refused.status_code == 401
        assert refused.json()["type"].endswith("/invalid-refresh-token")


async def test_e3_h5_ca2_an_account_under_review_cannot_log_in(api):
    user_id = await register_verified(api)
    await api.put_under_review(user_id, internal_token())

    response = await api.login()
    assert response.status_code == 403
    assert response.json()["type"].endswith("/account-under-review")
    # Its own message: the owner has to be able to tell it from a suspension.
    assert response.json()["detail"] == UNDER_REVIEW


async def test_e3_h5_ca2_an_administrator_under_review_cannot_open_the_backoffice(api):
    user_id = await register_verified(api)
    await set_user_flag(api.app, "role", "moderator")
    await api.put_under_review(user_id, internal_token())

    response = await api.admin_login()
    assert response.status_code == 403
    assert response.json()["type"].endswith("/account-under-review")


async def test_review_records_when_the_status_changed_and_no_reason(api):
    user_id = await register_verified(api)
    before = datetime.now(UTC)

    assert (await api.put_under_review(user_id, internal_token())).status_code == 204

    status, reason, changed_at = await stored_status(api, user_id)
    assert status == "under_review"
    # Nobody decided it: the reasons are the reports, and they live in posts-api.
    assert reason is None
    assert changed_at >= before


async def test_e3_h5_ca2_putting_an_account_under_review_twice_changes_nothing(api):
    user_id = await register_verified(api)

    assert (await api.put_under_review(user_id, internal_token())).status_code == 204
    assert (await api.put_under_review(user_id, internal_token())).status_code == 204
    assert (await api.login()).json()["type"].endswith("/account-under-review")


async def test_e3_h5_ca2_a_suspended_account_stays_suspended(api):
    user_id = await register_verified(api)
    blocked_at = datetime(2026, 10, 20, 9, tzinfo=UTC)
    await set_user_flag(api.app, "status", "suspended")
    await set_user_flag(api.app, "status_reason", "Spam reiterado")
    await set_user_flag(api.app, "status_changed_at", blocked_at)

    assert (await api.put_under_review(user_id, internal_token())).status_code == 204

    # Suspension is an administrator's decision; a report never softens it, nor
    # replaces the reason the administrator gave.
    response = await api.login()
    assert response.json()["detail"] == "Cuenta suspendida"
    assert await stored_status(api, user_id) == ("suspended", "Spam reiterado", blocked_at)


async def test_e3_h5_ca2_a_deleted_account_under_review_says_suspended(api):
    await register_verified(api)
    await set_user_flag(api.app, "status", "under_review")
    await set_user_flag(api.app, "deleted_at", datetime.now(UTC))

    response = await api.login()
    assert response.json()["detail"] == "Cuenta suspendida"


async def test_e3_h5_ca2_an_unknown_account_is_not_found(api):
    response = await api.put_under_review(str(uuid.uuid4()), internal_token())
    assert response.status_code == 404
    assert response.json()["type"].endswith("/account-not-found")


@pytest.mark.parametrize("sent", [None, "otro-token"])
async def test_e3_h5_ca4_the_internal_route_refuses_a_missing_or_wrong_token(api, sent):
    user_id = await register_verified(api)

    response = await api.put_under_review(user_id, sent)
    assert response.status_code == 401
    assert response.json()["type"].endswith("/invalid-internal-token")
    # Nothing happened to the account.
    assert (await api.login()).status_code == 200


async def test_e3_h5_ca4_the_internal_route_is_not_under_api(api):
    user_id = await register_verified(api)

    # The gateway only forwards /api; the route must not exist there.
    response = await api.client.post(
        f"/internal/users/{user_id}/review",
        headers={"X-Internal-Token": internal_token()},
    )
    assert response.status_code == 404
