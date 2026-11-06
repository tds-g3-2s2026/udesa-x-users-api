"""Reading and editing one's own preferences.

Twin of `test_profile.py`: same authentication, different resource. What is
specific to this one is the enum-backed values and the defaults a new account
gets without ever touching the endpoint.
"""

import importlib.util
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.schemas import validator_for
from users_api.infrastructure.database.outbox_repository import SqlAlchemyOutboxRepository

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL") or not os.getenv("RABBITMQ_URL"),
    reason="requires DATABASE_URL, REDIS_URL and RABBITMQ_URL pointing at real services",
)

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "0007_idioma_de_cuentas_existentes.py"
)


async def signed_in(api) -> str:
    await api.register_and_verify()
    return (await api.login()).json()["access_token"]


async def test_get_preferences_requires_authentication(api):
    response = await api.get_preferences("token-invalido")
    assert response.status_code == 401


async def test_e1_h7_ca5_registration_assigns_default_preferences(api):
    token = await signed_in(api)

    response = await api.get_preferences(token)
    assert response.status_code == 200
    assert response.json() == {"profile_visibility": "public", "feed_language": "all"}


async def test_e1_h7_ca1_profile_visibility_can_be_switched(api):
    token = await signed_in(api)

    response = await api.update_preferences(token, profile_visibility="protected")
    assert response.status_code == 200
    assert response.json()["profile_visibility"] == "protected"

    # And it persists: a separate read confirms it, and the other preference
    # was left as it was.
    preferences = await api.get_preferences(token)
    assert preferences.json() == {"profile_visibility": "protected", "feed_language": "all"}


async def test_e1_h7_ca2_feed_language_can_be_chosen(api):
    token = await signed_in(api)

    response = await api.update_preferences(token, feed_language="es")
    assert response.status_code == 200
    assert response.json()["feed_language"] == "es"


async def test_updating_one_preference_leaves_the_other_as_it_was(api):
    token = await signed_in(api)
    await api.update_preferences(token, profile_visibility="protected", feed_language="en")

    response = await api.update_preferences(token, feed_language="all")
    assert response.status_code == 200
    assert response.json() == {"profile_visibility": "protected", "feed_language": "all"}


async def test_an_unknown_preference_is_rejected_and_not_ignored(api):
    token = await signed_in(api)

    response = await api.update_preferences(token, theme="dark")
    assert response.status_code == 422
    assert [error["field"] for error in response.json()["errors"]] == ["theme"]

    # And nothing changed.
    assert (await api.get_preferences(token)).json()["feed_language"] == "all"


async def test_a_value_outside_the_enum_is_rejected(api):
    token = await signed_in(api)

    response = await api.update_preferences(token, profile_visibility="private")
    assert response.status_code == 422
    assert [error["field"] for error in response.json()["errors"]] == ["profile_visibility"]


async def language_events(api) -> list[dict]:
    return [e for e in await api.outbox_events() if e["type"] == "preferences.changed.v1"]


async def test_e1_h7_ca2_changing_the_language_queues_the_event(api):
    token = await signed_in(api)
    user_id = (await api.get_profile(token)).json()["id"]

    before = datetime.now(UTC)
    assert (await api.update_preferences(token, feed_language="es")).status_code == 200
    after = datetime.now(UTC)

    [event] = await language_events(api)
    validator_for("preferences.changed.v1").validate(event)
    assert event["data"] == {"user_id": user_id, "feed_language": "es"}
    # The instant of the change: the consumer orders by it. The envelope keeps
    # milliseconds, so the lower bound allows for the truncation.
    sent_at = datetime.fromisoformat(event["time"])
    assert before.replace(microsecond=before.microsecond // 1000 * 1000) <= sent_at <= after


async def test_every_real_change_queues_its_own_event(api):
    token = await signed_in(api)

    await api.update_preferences(token, feed_language="es")
    await api.update_preferences(token, feed_language="all")

    assert [e["data"]["feed_language"] for e in await language_events(api)] == ["es", "all"]


async def test_sending_the_same_language_queues_nothing(api):
    token = await signed_in(api)
    await api.update_preferences(token, feed_language="es")

    response = await api.update_preferences(token, feed_language="es")

    assert response.status_code == 200
    assert len(await language_events(api)) == 1


async def test_changing_only_the_visibility_queues_nothing(api):
    token = await signed_in(api)

    response = await api.update_preferences(token, profile_visibility="protected")

    assert response.status_code == 200
    assert await language_events(api) == []


async def test_the_migration_announces_only_living_accounts_that_chose_a_language(api):
    spec = importlib.util.spec_from_file_location("backfill", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    accounts = {
        "es@udesa.edu.ar": ("es", None),
        "en@udesa.edu.ar": ("en", None),
        "todos@udesa.edu.ar": ("all", None),
        "borrada@udesa.edu.ar": ("es", datetime.now(UTC)),
    }
    async with api.app.state.engine.begin() as connection:
        for number, (email, (language, deleted_at)) in enumerate(accounts.items()):
            await connection.execute(
                text(
                    "INSERT INTO users (id, email, handle, password_hash, must_change_password, "
                    "is_email_verified, terms_accepted, feed_language, deleted_at) VALUES "
                    "(gen_random_uuid(), :email, :handle, 'x', false, true, true, :language, "
                    ":deleted_at)"
                ),
                {
                    "email": email,
                    "handle": f"@cuenta{number}",
                    "language": language,
                    "deleted_at": deleted_at,
                },
            )
        await connection.execute(text(migration.QUEUE_CHOSEN_LANGUAGES))
        result = await connection.execute(
            text(
                "SELECT outbox.id, outbox.type, outbox.payload, users.email FROM outbox "
                "JOIN users ON users.id::text = outbox.payload->'data'->>'user_id'"
            )
        )
        rows = result.all()

    assert {row.email: row.payload["data"]["feed_language"] for row in rows} == {
        "es@udesa.edu.ar": "es",
        "en@udesa.edu.ar": "en",
    }
    for row in rows:
        # The same envelope `app/events.py` builds, and the columns the publisher
        # routes and deduplicates by.
        validator_for("preferences.changed.v1").validate(row.payload)
        assert row.type == "preferences.changed.v1"
        assert str(row.id) == row.payload["id"]


async def test_the_language_and_its_event_commit_or_roll_back_together(api, monkeypatch):
    token = await signed_in(api)

    async def failing_add(self, event):
        await self.session.flush()
        raise RuntimeError("the outbox write failed")

    with monkeypatch.context() as patch:
        patch.setattr(SqlAlchemyOutboxRepository, "add", failing_add)
        with pytest.raises(RuntimeError):
            await api.update_preferences(token, feed_language="es")

    assert (await api.get_preferences(token)).json()["feed_language"] == "all"
    assert await language_events(api) == []
