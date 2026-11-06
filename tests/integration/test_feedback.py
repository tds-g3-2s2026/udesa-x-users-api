"""Comments and bug reports sent from the app.

Each message leaves two things behind in one transaction: its record and the event
that becomes the email to the support account.
"""

import os
import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from tests.integration.helpers import REGISTRATION
from tests.schemas import validator_for
from users_api.infrastructure.database.models import FeedbackModel
from users_api.infrastructure.database.outbox_repository import SqlAlchemyOutboxRepository

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL") or not os.getenv("RABBITMQ_URL"),
    reason="requires DATABASE_URL, REDIS_URL and RABBITMQ_URL pointing at real services",
)

DEVICE = {"device_os": "Android 15", "app_version": "1.3.0"}


async def signed_in(api) -> str:
    await api.register_and_verify()
    return (await api.login()).json()["access_token"]


async def send(api, token: str, message: str = "La pantalla se queda cargando", **overrides):
    return await api.client.post(
        "/me/feedback",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": message, **DEVICE, **overrides},
    )


async def stored(api) -> list[FeedbackModel]:
    async with api.app.state.session_factory() as session:
        return list(await session.scalars(select(FeedbackModel)))


async def feedback_events(api) -> list[dict]:
    return [event for event in await api.outbox_events() if event["type"].startswith("feedback.")]


async def test_e1_h11_ca1_a_text_over_500_characters_is_rejected(api):
    token = await signed_in(api)

    too_long = await send(api, token, "a" * 501)
    assert too_long.status_code == 422
    assert [problem["field"] for problem in too_long.json()["errors"]] == ["message"]
    assert await stored(api) == []

    # Exactly at the limit it goes through.
    assert (await send(api, token, "a" * 500)).status_code == 201


async def test_e1_h11_ca2_sending_stores_it_and_queues_the_email(api):
    token = await signed_in(api)

    response = await send(api, token, "  La pantalla se queda cargando  ")
    assert response.status_code == 201
    user_id = (await api.get_profile(token)).json()["id"]

    [record] = await stored(api)
    assert str(record.id) == response.json()["id"]
    assert str(record.user_id) == user_id
    assert record.handle == REGISTRATION["handle"]
    assert record.message == "La pantalla se queda cargando"
    assert record.device_os == DEVICE["device_os"]
    assert record.app_version == DEVICE["app_version"]

    [event] = await feedback_events(api)
    validator_for("feedback.submitted.v1").validate(event)
    assert event["data"] == {
        "feedback_id": str(record.id),
        "user_id": user_id,
        "handle": record.handle,
        "message": record.message,
        **DEVICE,
    }
    assert abs((record.created_at - datetime.fromisoformat(event["time"])).total_seconds()) < 0.001


async def test_the_record_and_the_event_commit_or_roll_back_together(api, monkeypatch):
    token = await signed_in(api)

    async def failing_add(self, event):
        await self.session.flush()
        raise RuntimeError("the outbox write failed")

    monkeypatch.setattr(SqlAlchemyOutboxRepository, "add", failing_add)
    with pytest.raises(RuntimeError):
        await send(api, token)

    assert await stored(api) == []
    assert await feedback_events(api) == []


async def test_the_account_comes_from_the_session_and_not_from_the_body(api):
    token = await signed_in(api)
    somebody_else = str(uuid.uuid4())

    response = await send(api, token, user_id=somebody_else, handle="@otro")
    assert response.status_code == 201

    [record] = await stored(api)
    assert str(record.user_id) != somebody_else
    assert record.handle == REGISTRATION["handle"]


async def test_sending_requires_a_session(api):
    response = await api.client.post("/me/feedback", json={"message": "Hola", **DEVICE})
    assert response.status_code == 401
    assert await stored(api) == []


async def test_e1_h11_ca4_the_third_message_in_an_hour_gets_429(api):
    token = await signed_in(api)

    for _ in range(2):
        assert (await send(api, token)).status_code == 201

    blocked = await send(api, token)
    assert blocked.status_code == 429
    assert blocked.json()["type"].endswith("/too-many-feedback-messages")
    assert blocked.headers["Retry-After"] == str(60 * 60)
    # The refused one left nothing behind.
    assert len(await stored(api)) == 2
    assert len(await feedback_events(api)) == 2


async def test_the_limit_is_counted_per_account(api):
    token = await signed_in(api)
    for _ in range(2):
        await send(api, token)

    await api.register_and_verify(email="otra@udesa.edu.ar", handle="@otra_cuenta")
    other = (await api.login(identifier="otra@udesa.edu.ar")).json()["access_token"]

    assert (await send(api, other)).status_code == 201


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
async def test_e1_h11_ca5_only_spaces_is_rejected(api, blank):
    token = await signed_in(api)

    response = await send(api, token, blank)
    assert response.status_code == 422
    assert [problem["field"] for problem in response.json()["errors"]] == ["message"]
    assert await stored(api) == []
    assert await feedback_events(api) == []


async def test_a_rejected_text_does_not_spend_an_attempt(api):
    token = await signed_in(api)

    for _ in range(3):
        assert (await send(api, token, "   ")).status_code == 422

    assert (await send(api, token)).status_code == 201


@pytest.mark.parametrize("field", ["device_os", "app_version"])
async def test_the_device_data_is_required(api, field):
    token = await signed_in(api)

    response = await send(api, token, **{field: ""})
    assert response.status_code == 422
    assert [problem["field"] for problem in response.json()["errors"]] == [field]


@pytest.mark.parametrize("field", ["device_os", "app_version"])
@pytest.mark.parametrize("value", ["1.0\nAsunto: otro", "1.0\n", "1.0\r\nAsunto: otro"])
async def test_the_device_data_cannot_add_lines_to_the_email(api, field, value):
    token = await signed_in(api)

    response = await send(api, token, **{field: value})

    assert response.status_code == 422
    assert [problem["field"] for problem in response.json()["errors"]] == [field]
    assert await stored(api) == []
    assert await feedback_events(api) == []
