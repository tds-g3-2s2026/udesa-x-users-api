import asyncio
import contextlib
import json
import os
import uuid
from pathlib import Path

import aio_pika
import pytest
from aio_pika import DeliveryMode, ExchangeType, Message
from sqlalchemy import select

from users_api.api.event_handlers import build_event_handler
from users_api.infrastructure.database.models import AuditLogModel
from users_api.infrastructure.rabbitmq.event_consumer import (
    DEAD_LETTER_QUEUE,
    EXCHANGE,
    QUEUE,
    EventConsumer,
)

pytestmark = pytest.mark.skipif(
    not all(os.getenv(key) for key in ("DATABASE_URL", "REDIS_URL", "RABBITMQ_URL")),
    reason="requires PostgreSQL, Redis and RabbitMQ",
)


def event():
    schema = json.loads(Path("contracts/events/admin.action_recorded.v1.json").read_text())
    result = schema["examples"][0]
    result["id"] = str(uuid.uuid4())
    return result


async def eventually(check):
    async with asyncio.timeout(15):
        while not (result := await check()):
            await asyncio.sleep(0.05)
        return result


@pytest.fixture
async def consuming(api):
    connection = await aio_pika.connect_robust(os.environ["RABBITMQ_URL"])
    channel = await connection.channel()
    exchange = await channel.declare_exchange(EXCHANGE, ExchangeType.TOPIC, durable=True)
    real = build_event_handler(api.app.state.session_factory)
    state = {"failures": 0, "calls": 0, "attempts": []}

    async def handle(body):
        state["calls"] += 1
        state["attempts"].append(asyncio.get_running_loop().time())
        if state["failures"]:
            state["failures"] -= 1
            raise RuntimeError("database unavailable")
        return await real(body)

    consumer = EventConsumer(os.environ["RABBITMQ_URL"], handle, retry_seconds=0.1)
    task = asyncio.create_task(consumer.run())
    await asyncio.wait_for(consumer.ready.wait(), 15)
    await (await channel.declare_queue(QUEUE, passive=True)).purge()
    dead = await channel.declare_queue(DEAD_LETTER_QUEUE, passive=True)
    await dead.purge()
    yield exchange, dead, state
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    await connection.close()


async def publish(exchange, body):
    await exchange.publish(
        Message(body, delivery_mode=DeliveryMode.PERSISTENT), routing_key="admin.action_recorded.v1"
    )


async def test_e5_h6_ca1_broker_delivery_preserves_snapshot_and_deduplicates(api, consuming):
    exchange, _, state = consuming
    message = event()
    body = json.dumps(message).encode()
    await publish(exchange, body)
    await publish(exchange, body)

    async def recorded():
        async with api.app.state.session_factory() as session:
            rows = list(await session.scalars(select(AuditLogModel)))
            return rows if len(rows) == 1 and state["calls"] >= 2 else None

    [row] = await eventually(recorded)
    assert row.id == uuid.UUID(message["id"])
    assert row.actor_email == message["data"]["actor_email"]
    assert row.occurred_at.isoformat() == message["time"].replace("Z", "+00:00")


async def test_e5_h6_consumer_retries_database_failure(api, consuming):
    exchange, _, state = consuming
    state["failures"] = 2
    await publish(exchange, json.dumps(event()).encode())

    async def recorded():
        async with api.app.state.session_factory() as session:
            return await session.scalar(select(AuditLogModel.id))

    await eventually(recorded)
    assert state["calls"] == 3
    assert all(
        later - earlier >= 0.1
        for earlier, later in zip(state["attempts"], state["attempts"][1:], strict=False)
    )


async def test_e5_h6_invalid_message_is_sent_to_dead_letters(consuming):
    exchange, dead, _ = consuming
    await publish(exchange, b"invalid json")

    async def arrived():
        return await dead.get(fail=False)

    message = await eventually(arrived)
    assert message.body == b"invalid json"
    await message.ack()


async def test_e5_h6_dead_letters_are_isolated_from_other_services(consuming):
    exchange, dead, _ = consuming
    connection = await aio_pika.connect_robust(os.environ["RABBITMQ_URL"])
    async with connection:
        channel = await connection.channel(publisher_confirms=True)
        shared = await channel.declare_exchange(
            "udesa-x.events.dlx", ExchangeType.FANOUT, durable=True
        )
        other_dead = await channel.declare_queue(exclusive=True, auto_delete=True)
        await other_dead.bind(shared)
        other_source = await channel.declare_queue(
            exclusive=True,
            auto_delete=True,
            arguments={"x-dead-letter-exchange": shared.name},
        )
        await channel.default_exchange.publish(
            Message(b"other service rejected this"), routing_key=other_source.name
        )
        message = await other_source.get(timeout=5)
        await message.reject(requeue=False)

        async def other_arrived():
            return await other_dead.get(fail=False)

        message = await eventually(other_arrived)
        assert message.body == b"other service rejected this"
        await message.ack()
        assert await dead.get(fail=False) is None

        await publish(exchange, b"invalid audit")

        async def audit_arrived():
            return await dead.get(fail=False)

        message = await eventually(audit_arrived)
        assert message.body == b"invalid audit"
        await message.ack()
        assert await other_dead.get(fail=False) is None


async def test_e5_h6_handler_propagates_database_errors_and_can_retry(api, monkeypatch):
    handler = build_event_handler(api.app.state.session_factory)
    body = json.dumps(event()).encode()
    from users_api.infrastructure.database.audit_repository import SqlAlchemyAuditLogRepository

    original = SqlAlchemyAuditLogRepository.add

    async def fail(*args):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(SqlAlchemyAuditLogRepository, "add", fail)
    with pytest.raises(RuntimeError):
        await handler(body)
    monkeypatch.setattr(SqlAlchemyAuditLogRepository, "add", original)
    assert await handler(body) == "ack"


async def test_e5_h6_shutdown_waits_for_in_flight_audit_to_commit(api):
    entered = asyncio.Event()
    release = asyncio.Event()
    completed = asyncio.Event()
    real = build_event_handler(api.app.state.session_factory)

    async def handle(body):
        entered.set()
        await release.wait()
        result = await real(body)
        completed.set()
        return result

    connection = await aio_pika.connect_robust(os.environ["RABBITMQ_URL"])
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(EXCHANGE, ExchangeType.TOPIC, durable=True)
        consumer = EventConsumer(os.environ["RABBITMQ_URL"], handle, retry_seconds=0.1)
        task = asyncio.create_task(consumer.run())
        message = event()
        try:
            await asyncio.wait_for(consumer.ready.wait(), 15)
            await (await channel.declare_queue(QUEUE, passive=True)).purge()
            await publish(exchange, json.dumps(message).encode())
            await asyncio.wait_for(entered.wait(), 5)

            task.cancel()
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), 0.1)
            assert not completed.is_set()

            release.set()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
            assert completed.is_set()
            async with api.app.state.session_factory() as session:
                assert await session.get(AuditLogModel, uuid.UUID(message["id"])) is not None
        finally:
            release.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
