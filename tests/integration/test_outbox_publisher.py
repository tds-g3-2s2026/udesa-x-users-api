"""The publisher against a real RabbitMQ and a real PostgreSQL.

Each test binds its own exclusive queue, which disappears with the connection,
so nothing is left on the broker. The events that must find no queue use a type
nobody binds, so the result does not depend on what else runs on the broker.
"""

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import aio_pika
import pytest
from aio_pika import DeliveryMode, ExchangeType
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.schemas import validator_for
from users_api.app import events
from users_api.app.models.user import User
from users_api.infrastructure.database.models import OutboxModel
from users_api.infrastructure.database.session import build_session_factory
from users_api.infrastructure.rabbitmq import outbox_publisher
from users_api.infrastructure.rabbitmq.outbox_publisher import EXCHANGE, OutboxPublisher

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL") or not os.getenv("RABBITMQ_URL"),
    reason="requires DATABASE_URL, REDIS_URL and RABBITMQ_URL pointing at real services",
)

USER = User(
    id=uuid.uuid4(), email="alumno@udesa.edu.ar", handle="@alumno_01", password_hash="unused"
)
UNREACHABLE = "amqp://users:users@127.0.0.1:1"


@pytest.fixture
async def engine(clean_state):
    engine = create_async_engine(os.environ["DATABASE_URL"])
    yield engine
    await engine.dispose()


@pytest.fixture
async def queue():
    """A queue bound to the events these tests publish, gone when the test ends."""
    connection = await aio_pika.connect_robust(os.environ["RABBITMQ_URL"])
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(EXCHANGE, ExchangeType.TOPIC, durable=True)
        queue = await channel.declare_queue(exclusive=True, auto_delete=True)
        for routing_key in (events.USER_REGISTERED, events.PASSWORD_CHANGED):
            await queue.bind(exchange, routing_key)
        yield queue


def make_publisher(engine, *, poll_seconds: float = 60, rabbitmq_url: str | None = None):
    return OutboxPublisher(
        session_factory=build_session_factory(engine),
        database_url=os.environ["DATABASE_URL"],
        rabbitmq_url=rabbitmq_url or os.environ["RABBITMQ_URL"],
        poll_seconds=poll_seconds,
    )


async def insert(engine, envelope: dict, *, created_at: datetime | None = None) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO outbox (id, type, payload, created_at) "
                "VALUES (:id, :type, CAST(:payload AS jsonb), COALESCE(:created_at, now()))"
            ),
            {
                "id": uuid.UUID(envelope["id"]),
                "type": envelope["type"],
                "payload": json.dumps(envelope),
                "created_at": created_at,
            },
        )


async def pending(engine) -> list[str]:
    async with engine.connect() as connection:
        rows = await connection.scalars(select(OutboxModel.id).order_by(OutboxModel.created_at))
        return [str(row) for row in rows]


def unbound_event() -> dict:
    envelope = events.password_changed(USER, now=datetime.now(UTC)).envelope
    # A type that no queue is bound to, so the broker returns the message.
    return {**envelope, "id": str(uuid.uuid4()), "type": f"test.unbound.{uuid.uuid4().hex}.v1"}


async def next_message(queue, timeout: float = 10):
    async with asyncio.timeout(timeout):
        while (message := await queue.get(fail=False)) is None:
            await asyncio.sleep(0.05)
    return message


async def test_a_pass_delivers_the_event_with_the_contract_and_deletes_the_row(engine, queue):
    event = events.user_registered(
        USER,
        verification_url="https://udesa-x.example/api/auth/verify?token=abc",
        now=datetime.now(UTC),
    )
    await insert(engine, event.envelope)
    publisher = make_publisher(engine)

    try:
        await publisher.drain()
    finally:
        await publisher.close()

    message = await next_message(queue)
    await message.ack()
    assert json.loads(message.body.decode("utf-8")) == event.envelope
    validator_for(event.type).validate(json.loads(message.body))
    assert message.routing_key == event.type
    assert message.exchange == EXCHANGE
    assert message.content_type == "application/json"
    assert message.delivery_mode == DeliveryMode.PERSISTENT
    assert message.message_id == str(event.id)
    assert message.type == event.type
    assert await pending(engine) == []


async def test_without_a_bound_queue_the_row_stays(engine):
    envelope = unbound_event()
    await insert(engine, envelope)
    publisher = make_publisher(engine)

    try:
        await publisher.drain()
    finally:
        await publisher.close()

    # mandatory: the broker handed the message back, and a message that reached
    # nobody is not a delivered one.
    assert await pending(engine) == [envelope["id"]]


async def test_a_returned_event_stays_without_holding_back_the_ones_behind_it(engine, queue):
    now = datetime.now(UTC)
    first = events.password_changed(USER, now=now).envelope
    stuck = unbound_event()
    last = events.password_changed(USER, now=now).envelope
    for index, envelope in enumerate((first, stuck, last)):
        await insert(engine, envelope, created_at=now + timedelta(seconds=index))
    publisher = make_publisher(engine)

    try:
        await publisher.drain()
    finally:
        await publisher.close()

    # The one nobody is bound to waits in the outbox; the ones around it went out.
    assert await pending(engine) == [stuck["id"]]
    delivered = []
    for _ in range(2):
        message = await next_message(queue)
        await message.ack()
        delivered.append(message.message_id)
    assert delivered == [first["id"], last["id"]]


async def test_a_broker_lost_mid_pass_keeps_what_was_confirmed_and_leaves_the_rest(engine, queue):
    now = datetime.now(UTC)
    first, second, third = (events.password_changed(USER, now=now).envelope for _ in range(3))
    for index, envelope in enumerate((first, second, third)):
        await insert(engine, envelope, created_at=now + timedelta(seconds=index))
    publisher = make_publisher(engine)
    await publisher.connect()
    publish = publisher.publish
    attempted = []

    async def lose_the_broker_before_the_second(row):
        attempted.append(str(row.id))
        if str(row.id) == second["id"]:
            await publisher.connection.close()
        await publish(row)

    publisher.publish = lose_the_broker_before_the_second
    try:
        published, interrupted = await publisher.publish_batch()
    finally:
        await publisher.close()

    # Not a returned message: the pass stops there instead of trying the third.
    # Against a broker that is really gone each try would wait out the publish
    # timeout while holding the row locks. The delete of the first, already at
    # the broker, is still committed.
    assert attempted == [first["id"], second["id"]]
    assert (published, interrupted) == (1, True)
    assert await pending(engine) == [second["id"], third["id"]]
    message = await next_message(queue)
    await message.ack()
    assert message.message_id == first["id"]


async def test_a_refused_exchange_declaration_closes_the_connection(engine, monkeypatch):
    # An exchange that already exists with another type: the broker closes the
    # channel instead of declaring it.
    name = f"test.conflict.{uuid.uuid4().hex}"
    admin = await aio_pika.connect_robust(os.environ["RABBITMQ_URL"])
    async with admin:
        channel = await admin.channel()
        conflicting = await channel.declare_exchange(name, ExchangeType.FANOUT, auto_delete=False)
        monkeypatch.setattr(outbox_publisher, "EXCHANGE", name)
        opened = []
        connect_robust = aio_pika.connect_robust

        async def recording_connect(*args, **kwargs):
            connection = await connect_robust(*args, **kwargs)
            opened.append(connection)
            return connection

        monkeypatch.setattr(aio_pika, "connect_robust", recording_connect)
        publisher = make_publisher(engine)
        try:
            with pytest.raises(aio_pika.exceptions.ChannelPreconditionFailed):
                await publisher.connect()
        finally:
            await conflicting.delete()

    # Nothing half open is kept or leaked: the next pass starts from scratch.
    assert publisher.connection is None
    assert [connection.is_closed for connection in opened] == [True]


async def test_a_notification_wakes_the_publisher_before_the_poll_does(engine, queue):
    publisher = make_publisher(engine, poll_seconds=60)
    task = asyncio.create_task(publisher.run())
    try:
        # Let the first, empty pass finish and the listener attach.
        await asyncio.sleep(1)
        event = events.password_changed(USER, now=datetime.now(UTC))
        await insert(engine, event.envelope)

        message = await next_message(queue, timeout=5)
        await message.ack()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert message.message_id == str(event.id)
    assert await pending(engine) == []


async def test_polling_publishes_even_when_the_listener_is_lost(engine, queue):
    publisher = make_publisher(engine, poll_seconds=0.3)
    # A listener that can never connect: only the polling is left to find rows.
    publisher.listen_args = {**publisher.listen_args, "port": 1}
    event = events.password_changed(USER, now=datetime.now(UTC))
    await insert(engine, event.envelope)
    task = asyncio.create_task(publisher.run())
    try:
        message = await next_message(queue, timeout=5)
        await message.ack()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert message.message_id == str(event.id)


async def test_the_publisher_survives_an_unreachable_broker_and_keeps_the_rows(engine):
    event = events.password_changed(USER, now=datetime.now(UTC))
    await insert(engine, event.envelope)
    publisher = make_publisher(engine, poll_seconds=0.1, rabbitmq_url=UNREACHABLE)
    task = asyncio.create_task(publisher.run())

    await asyncio.sleep(0.6)

    # Still running after several failed passes, and nothing was lost.
    assert not task.done()
    assert await pending(engine) == [str(event.id)]
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
