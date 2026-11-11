"""The inbox of comments and bug reports, from the backoffice.

A message is listed with the handle it was sent with and whether its sender still has
an account, and an administrator moves it forward from pending to read or resolved.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert, text

from tests.integration.helpers import REGISTRATION, set_user_flag
from users_api.infrastructure.database.models import FeedbackModel

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL") or not os.getenv("RABBITMQ_URL"),
    reason="requires DATABASE_URL, REDIS_URL and RABBITMQ_URL pointing at real services",
)

SENDER = {"email": "remitente@udesa.edu.ar", "handle": "@remitente"}
DEVICE = {"device_os": "Android 15", "app_version": "1.3.0"}
NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)


async def administrator(api) -> dict[str, str]:
    """The registered account, promoted, and the headers of its backoffice session.

    Promoted before any other account exists: `set_user_flag` updates every row.
    """
    await api.register_and_verify()
    await set_user_flag(api.app, "role", "moderator")
    token = (await api.admin_login()).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def sender_sends(api, message: str = "La pantalla se queda cargando") -> tuple[str, str]:
    """A second account that sends a message from the app: its token and the message id."""
    await api.register_and_verify(**SENDER)
    token = (await api.login(identifier=SENDER["email"])).json()["access_token"]
    response = await api.client.post(
        "/me/feedback",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": message, **DEVICE},
    )
    assert response.status_code == 201
    return token, response.json()["id"]


async def given_feedback(api, *, created_at: datetime = NOW, status: str = "pending") -> str:
    """A message straight into the table, with its date and status under control."""
    feedback_id = uuid.uuid4()
    async with api.app.state.engine.begin() as connection:
        await connection.execute(
            insert(FeedbackModel).values(
                id=feedback_id,
                user_id=uuid.uuid4(),
                handle="@alguien",
                message="Algo falla",
                created_at=created_at,
                status=status,
                **DEVICE,
            )
        )
    return str(feedback_id)


async def inbox(api, headers, **params):
    return await api.client.get("/admin/feedback", headers=headers, params=params)


async def ids_in(api, headers, status: str) -> list[str]:
    return [item["id"] for item in (await inbox(api, headers, status=status)).json()["items"]]


async def move(api, headers, feedback_id: str, action: str):
    return await api.client.post(f"/admin/feedback/{feedback_id}/{action}", headers=headers)


async def test_e5_h12_ca1_lists_text_user_device_and_date(api):
    headers = await administrator(api)
    before = datetime.now(UTC)
    _, feedback_id = await sender_sends(api)
    after = datetime.now(UTC)

    response = await inbox(api, headers)

    assert response.status_code == 200
    [item] = response.json()["items"]
    sent_at = datetime.fromisoformat(item.pop("created_at"))
    assert before <= sent_at <= after
    assert item == {
        "id": feedback_id,
        "user_id": item["user_id"],
        "handle": SENDER["handle"],
        "account_available": True,
        "message": "La pantalla se queda cargando",
        "device_os": "Android 15",
        "app_version": "1.3.0",
        "status": "pending",
    }
    assert response.json()["next_cursor"] is None


async def test_e5_h12_ca2_a_resolved_message_leaves_the_inbox(api):
    headers = await administrator(api)
    kept = await given_feedback(api)
    resolved = await given_feedback(api, created_at=NOW - timedelta(minutes=1))

    assert (await move(api, headers, resolved, "resolve")).status_code == 204

    assert await ids_in(api, headers, "pending") == [kept]
    assert await ids_in(api, headers, "resolved") == [resolved]


async def test_e5_h12_ca3_the_message_survives_the_account_deletion(api):
    headers = await administrator(api)
    token, feedback_id = await sender_sends(api)

    deleted = await api.delete_account(token, REGISTRATION["password"])
    assert deleted.status_code == 200

    [item] = (await inbox(api, headers)).json()["items"]
    assert (item["id"], item["handle"], item["account_available"]) == (
        feedback_id,
        SENDER["handle"],
        False,
    )


async def test_a_blocked_sender_keeps_the_message_and_the_link_to_the_account(api):
    headers = await administrator(api)
    _, feedback_id = await sender_sends(api)
    async with api.app.state.engine.begin() as connection:
        await connection.execute(
            text("UPDATE users SET status = 'suspended' WHERE handle = :handle"),
            {"handle": SENDER["handle"]},
        )

    [item] = (await inbox(api, headers)).json()["items"]
    assert (item["id"], item["account_available"]) == (feedback_id, True)


async def test_a_message_read_moves_forward_and_never_back(api):
    headers = await administrator(api)
    feedback_id = await given_feedback(api)

    assert (await move(api, headers, feedback_id, "read")).status_code == 204
    assert await ids_in(api, headers, "pending") == []
    assert await ids_in(api, headers, "read") == [feedback_id]

    assert (await move(api, headers, feedback_id, "resolve")).status_code == 204
    assert (await move(api, headers, feedback_id, "read")).status_code == 204
    assert await ids_in(api, headers, "read") == []
    assert await ids_in(api, headers, "resolved") == [feedback_id]


async def test_resolving_twice_is_not_an_error(api):
    headers = await administrator(api)
    feedback_id = await given_feedback(api, status="resolved")

    assert (await move(api, headers, feedback_id, "resolve")).status_code == 204
    assert await ids_in(api, headers, "resolved") == [feedback_id]


@pytest.mark.parametrize("action", ["read", "resolve"])
async def test_an_unknown_message_is_404(api, action):
    headers = await administrator(api)

    response = await move(api, headers, str(uuid.uuid4()), action)

    assert response.status_code == 404
    assert response.json()["type"].endswith("/feedback-not-found")


@pytest.mark.parametrize("action", ["read", "resolve"])
async def test_an_id_that_is_not_a_uuid_is_422(api, action):
    headers = await administrator(api)

    assert (await move(api, headers, "no-es-un-uuid", action)).status_code == 422


async def test_the_inbox_shows_twenty_per_page_newest_first(api):
    headers = await administrator(api)
    created = [await given_feedback(api, created_at=NOW - timedelta(minutes=i)) for i in range(21)]

    first = (await inbox(api, headers)).json()
    second = (await inbox(api, headers, cursor=first["next_cursor"])).json()

    assert [item["id"] for item in first["items"]] == created[:20]
    assert [item["id"] for item in second["items"]] == created[20:]
    assert second["next_cursor"] is None


async def test_an_unknown_status_is_422(api):
    headers = await administrator(api)

    assert (await inbox(api, headers, status="archived")).status_code == 422


async def test_a_tampered_cursor_is_400(api):
    headers = await administrator(api)

    response = await inbox(api, headers, cursor="no-es-un-cursor")

    assert response.status_code == 400
    assert response.json()["type"].endswith("/invalid-cursor")


async def test_without_a_token_the_inbox_is_401(api):
    assert (await api.client.get("/admin/feedback")).status_code == 401
    assert (await api.client.post(f"/admin/feedback/{uuid.uuid4()}/read")).status_code == 401


async def test_an_app_account_cannot_reach_the_inbox(api):
    token, feedback_id = await sender_sends(api)
    headers = {"Authorization": f"Bearer {token}"}

    assert (await inbox(api, headers)).status_code == 403
    assert (await move(api, headers, feedback_id, "resolve")).status_code == 403
