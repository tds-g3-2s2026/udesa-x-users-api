"""What the requests leave in the outbox, and that RabbitMQ is never in their way.

The publisher itself is covered in `test_outbox_publisher.py`. Here the broker
is unreachable (see the `api` fixture), which is exactly the situation the
definition of done asks the service to survive.
"""

import asyncio
import os

import pytest
from sqlalchemy import func, select

from tests.integration.helpers import REGISTRATION
from users_api.infrastructure.database.models import OutboxModel, UserModel
from users_api.infrastructure.database.outbox_repository import SqlAlchemyOutboxRepository

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL") or not os.getenv("RABBITMQ_URL"),
    reason="requires DATABASE_URL, REDIS_URL and RABBITMQ_URL pointing at real services",
)


async def count(api, model) -> int:
    async with api.app.state.engine.connect() as connection:
        return await connection.scalar(select(func.count()).select_from(model))


async def test_registering_leaves_user_registered_in_the_outbox(api):
    response = await api.register()

    assert response.status_code == 201
    events = await api.outbox_events()
    assert [event["type"] for event in events] == ["user.registered.v1"]
    data = events[0]["data"]
    assert data["email"] == REGISTRATION["email"].lower()
    assert data["handle"] == REGISTRATION["handle"]
    assert data["user_id"] == response.json()["id"]
    assert data["verification_url"].startswith("http")


async def test_a_failed_registration_leaves_no_event(api):
    assert (await api.register()).status_code == 201
    assert len(await api.outbox_events()) == 1

    duplicate = await api.register()

    assert duplicate.status_code == 409
    # Still only the first account's event.
    assert len(await api.outbox_events()) == 1


async def test_the_event_and_the_account_commit_or_roll_back_together(api, monkeypatch):
    async def failing_add(self, event):
        await self.session.flush()
        raise RuntimeError("the outbox write failed")

    monkeypatch.setattr(SqlAlchemyOutboxRepository, "add", failing_add)

    with pytest.raises(RuntimeError):
        await api.register()

    # The account was written in the same session before the event failed: one
    # transaction, so neither survives.
    assert await count(api, UserModel) == 0
    assert await count(api, OutboxModel) == 0


async def test_asking_for_a_new_link_queues_a_request_and_not_a_second_registration(api):
    await api.register()

    response = await api.client.post(
        "/auth/resend-verification", json={"email": REGISTRATION["email"]}
    )

    assert response.status_code == 202
    first, second = await api.outbox_events()
    assert [first["type"], second["type"]] == [
        "user.registered.v1",
        "email_verification.requested.v1",
    ]
    assert first["id"] != second["id"]
    assert first["data"]["verification_url"] != second["data"]["verification_url"]


async def test_asking_for_a_reset_queues_the_code_only_for_a_real_account(api):
    await api.register_and_verify()
    registered = len(await api.outbox_events())

    assert (await api.forgot_password("nadie@udesa.edu.ar")).status_code == 202
    assert len(await api.outbox_events()) == registered

    assert (await api.forgot_password()).status_code == 202
    event = await api.last_event()
    assert event["type"] == "password.reset_requested.v1"
    assert event["data"]["email"] == REGISTRATION["email"].lower()
    assert event["data"]["token"]


async def test_the_api_answers_and_the_events_wait_while_rabbitmq_is_unreachable(api):
    response = await api.register()

    assert response.status_code == 201
    # Long enough for several failed passes of the publisher, which runs in the
    # lifespan against a broker that refuses the connection.
    await asyncio.sleep(0.5)
    assert await count(api, OutboxModel) == 1
    # Nothing else is affected: the account works as usual.
    await api.verify_last()
    assert (await api.login()).status_code == 200
