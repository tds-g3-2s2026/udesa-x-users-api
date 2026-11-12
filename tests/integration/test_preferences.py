"""Reading and editing one's own preferences.

Twin of `test_profile.py`: same authentication, different resource. What is
specific to this one is the enum-backed values and the defaults a new account
gets without ever touching the endpoint.
"""

import importlib.util
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.schemas import validator_for
from users_api.app.models.user import FeedLanguage
from users_api.app.services.preferences import PreferencesService
from users_api.infrastructure.database.outbox_repository import SqlAlchemyOutboxRepository
from users_api.infrastructure.database.user_repository import SqlAlchemyUserRepository

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
VISIBILITY_MIGRATION = MIGRATION.with_name("0011_visibilidad_de_cuentas_existentes.py")


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
    assert response.json() == {
        "profile_visibility": "public",
        "feed_language": "all",
        "interests": [],
    }


async def test_e1_h7_ca1_profile_visibility_can_be_switched(api):
    token = await signed_in(api)

    response = await api.update_preferences(token, profile_visibility="protected")
    assert response.status_code == 200
    assert response.json()["profile_visibility"] == "protected"

    # And it persists: a separate read confirms it, and the other preference
    # was left as it was.
    preferences = await api.get_preferences(token)
    assert preferences.json() == {
        "profile_visibility": "protected",
        "feed_language": "all",
        "interests": [],
    }


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
    assert response.json() == {
        "profile_visibility": "protected",
        "feed_language": "all",
        "interests": [],
    }


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


async def preference_events(api) -> list[dict]:
    return [e for e in await api.outbox_events() if e["type"] == "preferences.changed.v1"]


async def test_e1_h7_ca2_changing_the_language_queues_the_event(api):
    token = await signed_in(api)
    user_id = (await api.get_profile(token)).json()["id"]

    before = datetime.now(UTC)
    assert (await api.update_preferences(token, feed_language="es")).status_code == 200
    after = datetime.now(UTC)

    [event] = await preference_events(api)
    validator_for("preferences.changed.v1").validate(event)
    assert event["data"] == {
        "user_id": user_id,
        "feed_language": "es",
        "profile_visibility": "public",
    }
    # The instant of the change: the consumer orders by it. The envelope keeps
    # milliseconds, so the lower bound allows for the truncation.
    sent_at = datetime.fromisoformat(event["time"])
    assert before.replace(microsecond=before.microsecond // 1000 * 1000) <= sent_at <= after


async def test_every_real_change_queues_its_own_event(api):
    token = await signed_in(api)

    await api.update_preferences(token, feed_language="es")
    await api.update_preferences(token, feed_language="all")

    assert [e["data"]["feed_language"] for e in await preference_events(api)] == ["es", "all"]


async def test_sending_the_same_language_queues_nothing(api):
    token = await signed_in(api)
    await api.update_preferences(token, feed_language="es")

    response = await api.update_preferences(token, feed_language="es")

    assert response.status_code == 200
    assert len(await preference_events(api)) == 1


async def test_e1_h7_ca1_changing_the_visibility_queues_the_event(api):
    token = await signed_in(api)
    user_id = (await api.get_profile(token)).json()["id"]

    response = await api.update_preferences(token, profile_visibility="protected")

    assert response.status_code == 200
    [event] = await preference_events(api)
    validator_for("preferences.changed.v1").validate(event)
    assert event["data"] == {
        "user_id": user_id,
        "feed_language": "all",
        "profile_visibility": "protected",
    }


async def test_sending_the_same_visibility_queues_nothing(api):
    token = await signed_in(api)
    await api.update_preferences(token, profile_visibility="protected")

    response = await api.update_preferences(token, profile_visibility="protected")

    assert response.status_code == 200
    assert len(await preference_events(api)) == 1


async def test_changing_both_preferences_at_once_queues_one_event(api):
    token = await signed_in(api)

    await api.update_preferences(token, profile_visibility="protected", feed_language="en")

    [event] = await preference_events(api)
    assert event["data"]["profile_visibility"] == "protected"
    assert event["data"]["feed_language"] == "en"


async def test_an_edit_announces_the_account_as_stored_and_not_as_the_request_first_read_it(api):
    token = await signed_in(api)
    user_id = uuid.UUID((await api.get_profile(token)).json()["id"])
    async with api.app.state.session_factory() as session:
        stale = await SqlAlchemyUserRepository(session).get(user_id)
    await api.update_preferences(token, profile_visibility="protected")

    async with api.app.state.session_factory() as session, session.begin():
        service = PreferencesService(
            users=SqlAlchemyUserRepository(session), outbox=SqlAlchemyOutboxRepository(session)
        )
        await service.update_preferences(stale, changes={"feed_language": FeedLanguage.ES})

    *_, last = await preference_events(api)
    assert last["data"]["profile_visibility"] == "protected"
    assert last["data"]["feed_language"] == "es"
    assert (await api.get_preferences(token)).json()["profile_visibility"] == "protected"


async def test_an_event_carries_the_other_preference_as_it_stands(api):
    token = await signed_in(api)
    await api.update_preferences(token, profile_visibility="protected")

    await api.update_preferences(token, feed_language="en")

    [_, event] = await preference_events(api)
    assert event["data"]["profile_visibility"] == "protected"
    assert event["data"]["feed_language"] == "en"


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


async def test_the_visibility_migration_announces_every_living_account(api):
    spec = importlib.util.spec_from_file_location("visibility_backfill", VISIBILITY_MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    accounts = {
        "publica@udesa.edu.ar": ("public", "all", None),
        "protegida@udesa.edu.ar": ("protected", "es", None),
        "borrada@udesa.edu.ar": ("protected", "all", datetime.now(UTC)),
    }
    async with api.app.state.engine.begin() as connection:
        for number, (email, (visibility, language, deleted_at)) in enumerate(accounts.items()):
            await connection.execute(
                text(
                    "INSERT INTO users (id, email, handle, password_hash, must_change_password, "
                    "is_email_verified, terms_accepted, profile_visibility, feed_language, "
                    "deleted_at) VALUES (gen_random_uuid(), :email, :handle, 'x', false, true, "
                    "true, :visibility, :language, :deleted_at)"
                ),
                {
                    "email": email,
                    "handle": f"@cuenta{number}",
                    "visibility": visibility,
                    "language": language,
                    "deleted_at": deleted_at,
                },
            )
        await connection.execute(text(migration.QUEUE_CURRENT_PREFERENCES))
        result = await connection.execute(
            text(
                "SELECT outbox.id, outbox.type, outbox.payload, users.email FROM outbox "
                "JOIN users ON users.id::text = outbox.payload->'data'->>'user_id'"
            )
        )
        rows = result.all()

    assert {
        row.email: (row.payload["data"]["profile_visibility"], row.payload["data"]["feed_language"])
        for row in rows
    } == {"publica@udesa.edu.ar": ("public", "all"), "protegida@udesa.edu.ar": ("protected", "es")}
    for row in rows:
        validator_for("preferences.changed.v1").validate(row.payload)
        assert row.type == "preferences.changed.v1"
        assert str(row.id) == row.payload["id"]
        # Older than any real change, so it only fills the copies that have no event.
        assert row.payload["time"] == "1970-01-01T00:00:00.000Z"


async def test_the_preferences_and_their_event_commit_or_roll_back_together(api, monkeypatch):
    token = await signed_in(api)

    async def failing_add(self, event):
        await self.session.flush()
        raise RuntimeError("the outbox write failed")

    with monkeypatch.context() as patch:
        patch.setattr(SqlAlchemyOutboxRepository, "add", failing_add)
        with pytest.raises(RuntimeError):
            await api.update_preferences(token, feed_language="es")

    assert (await api.get_preferences(token)).json()["feed_language"] == "all"
    assert await preference_events(api) == []


THREE = ["music", "sports", "gaming"]


async def test_e1_h14_ca2_fewer_than_three_interests_are_rejected(api):
    token = await signed_in(api)

    response = await api.update_preferences(token, interests=["sports", "music"])

    assert response.status_code == 422
    assert [error["field"] for error in response.json()["errors"]] == ["interests"]
    assert (await api.get_preferences(token)).json()["interests"] == []


async def test_the_interests_come_back_in_the_order_they_were_sent(api):
    token = await signed_in(api)

    response = await api.update_preferences(token, interests=THREE)

    assert response.status_code == 200
    assert response.json()["interests"] == THREE
    assert (await api.get_preferences(token)).json()["interests"] == THREE


async def test_sending_the_interests_replaces_the_whole_list(api):
    token = await signed_in(api)
    await api.update_preferences(token, interests=THREE)

    replacement = ["economy", "science", "politics", "technology"]
    response = await api.update_preferences(token, interests=replacement)

    assert response.json()["interests"] == replacement


@pytest.mark.parametrize(
    "interests",
    [
        ["sports", "music", "cooking"],
        ["sports", "sports", "music"],
        None,
    ],
    ids=["unknown", "repeated", "null"],
)
async def test_an_invalid_list_of_interests_is_rejected_on_the_field(api, interests):
    token = await signed_in(api)

    response = await api.update_preferences(token, interests=interests)

    assert response.status_code == 422
    assert [error["field"] for error in response.json()["errors"]] == ["interests"]
    assert (await api.get_preferences(token)).json()["interests"] == []


async def test_choosing_interests_leaves_the_other_preferences_and_queues_nothing(api):
    token = await signed_in(api)

    response = await api.update_preferences(token, interests=THREE)

    assert response.json() == {
        "profile_visibility": "public",
        "feed_language": "all",
        "interests": THREE,
    }
    assert await preference_events(api) == []
