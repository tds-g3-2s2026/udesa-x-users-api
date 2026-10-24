"""Every event the service builds, validated against its published schema.

The schemas under `contracts/events/` are the contract with the consumers
(ADR-017), checked with their formats switched on (see `tests/schemas.py`).
"""

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest

from tests.schemas import validator_for
from users_api.app import events
from users_api.app.models.user import User

NOW = datetime(2026, 10, 24, 10, 15, 2, 123456, tzinfo=UTC)
USER = User(
    id=uuid.uuid4(),
    email="alumno@udesa.edu.ar",
    handle="alumno_01",
    password_hash="unused",
)
VERIFICATION_URL = "https://udesa-x.example/api/auth/verify?token=Zk3pQ9vX2mLr8sT1"

BUILT = {
    "user.registered.v1": lambda: events.user_registered(
        USER, verification_url=VERIFICATION_URL, now=NOW
    ),
    "email_verification.requested.v1": lambda: events.email_verification_requested(
        USER, verification_url=VERIFICATION_URL, now=NOW
    ),
    "password.reset_requested.v1": lambda: events.password_reset_requested(
        USER, token="Xc5vB8nM2kLj6hGf", now=NOW
    ),
    "password.changed.v1": lambda: events.password_changed(USER, now=NOW),
}


@pytest.mark.parametrize("event_type", BUILT)
def test_each_event_validates_against_its_schema(event_type):
    event = BUILT[event_type]()

    validator_for(event_type).validate(event.envelope)
    assert event.type == event_type


def test_the_formats_are_actually_enforced():
    # Guards the guard: if the format checker silently did nothing, the test
    # above would pass with garbage in the fields.
    envelope = {**BUILT["password.changed.v1"]().envelope, "id": "not-a-uuid"}

    assert list(validator_for("password.changed.v1").iter_errors(envelope))


@pytest.mark.parametrize("event_type", BUILT)
def test_the_envelope_is_a_cloudevent_with_a_fresh_id_and_a_utc_time(event_type):
    first, second = BUILT[event_type](), BUILT[event_type]()

    assert first.envelope["specversion"] == "1.0"
    assert first.envelope["source"] == "users-api"
    assert first.envelope["time"] == "2026-10-24T10:15:02.123Z"
    # The id is what the consumer deduplicates on: two events never share it.
    assert first.id != second.id
    assert str(first.id) == first.envelope["id"]


def test_the_time_is_converted_to_utc():
    local = NOW.astimezone(timezone(timedelta(hours=-3)))

    event = events.password_changed(USER, now=local)

    assert event.envelope["time"] == "2026-10-24T10:15:02.123Z"
