"""Reading and editing one's own profile.

`GET /me` and `PATCH /me` are the first pair of endpoints in the service that
only make sense to call while authenticated, so a good part of what gets
tested here is that authentication itself, not only the profile.
"""

import os
import uuid

import anyio
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.helpers import REGISTRATION, set_user_flag

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL") or not os.getenv("RABBITMQ_URL"),
    reason="requires DATABASE_URL, REDIS_URL and RABBITMQ_URL pointing at real services",
)


async def signed_in(api) -> str:
    await api.register_and_verify()
    return (await api.login()).json()["access_token"]


async def test_get_profile_requires_authentication(api):
    response = await api.get_profile("token-invalido")
    assert response.status_code == 401


async def test_get_profile_returns_the_account(api):
    token = await signed_in(api)

    response = await api.get_profile(token)
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == REGISTRATION["email"].lower()
    assert body["handle"] == REGISTRATION["handle"]
    assert body["display_name"] is None
    assert body["bio"] is None


async def test_e1_h6_ca2_email_cannot_be_changed(api):
    token = await signed_in(api)

    response = await api.update_profile(token, email="otro@udesa.edu.ar")
    assert response.status_code == 422
    assert [error["field"] for error in response.json()["errors"]] == ["email"]

    # And the attempt changed nothing.
    assert (await api.get_profile(token)).json()["email"] == REGISTRATION["email"].lower()


async def test_e1_h6_ca3_updates_bio_and_display_name(api):
    token = await signed_in(api)

    response = await api.update_profile(token, display_name="Juan Perez", bio="Estudiante")
    assert response.status_code == 200
    assert response.json()["display_name"] == "Juan Perez"
    assert response.json()["bio"] == "Estudiante"

    # It persists: a separate read confirms it.
    profile = await api.get_profile(token)
    assert profile.json()["display_name"] == "Juan Perez"
    assert profile.json()["bio"] == "Estudiante"


async def test_updating_one_field_leaves_the_other_as_it_was(api):
    token = await signed_in(api)
    await api.update_profile(token, display_name="Juan Perez", bio="Estudiante")

    response = await api.update_profile(token, bio="Nueva bio")
    assert response.status_code == 200
    assert response.json() == {
        "id": response.json()["id"],
        "email": REGISTRATION["email"].lower(),
        "handle": REGISTRATION["handle"],
        "display_name": "Juan Perez",
        "bio": "Nueva bio",
        "onboarding_completed": False,
    }


async def test_update_profile_sanitizes_html_before_storing_it(api):
    token = await signed_in(api)

    response = await api.update_profile(
        token,
        display_name="<b>Juan</b> Perez",
        bio="<script>alert(1)</script>Hola",
    )
    assert response.status_code == 200
    assert response.json()["display_name"] == "Juan Perez"
    assert response.json()["bio"] == "Hola"


# The migration before the one that adds the onboarding.
BEFORE_ONBOARDING = "e27b5d83a1c4"


async def complete_onboarding(api, token: str):
    return await api.client.post(
        "/me/onboarding/complete", headers={"Authorization": f"Bearer {token}"}
    )


async def test_a_new_account_has_not_done_the_onboarding(api):
    token = await signed_in(api)

    assert (await api.get_profile(token)).json()["onboarding_completed"] is False


async def test_completing_the_onboarding_marks_it_done(api):
    token = await signed_in(api)
    await api.update_preferences(token, interests=["music", "sports", "gaming"])

    response = await complete_onboarding(api, token)

    assert response.status_code == 204
    assert response.content == b""
    assert (await api.get_profile(token)).json()["onboarding_completed"] is True


async def test_completing_the_onboarding_twice_is_not_an_error(api):
    token = await signed_in(api)
    await api.update_preferences(token, interests=["music", "sports", "gaming"])
    await complete_onboarding(api, token)

    assert (await complete_onboarding(api, token)).status_code == 204


async def test_the_onboarding_cannot_finish_without_three_interests(api):
    token = await signed_in(api)

    response = await complete_onboarding(api, token)

    assert response.status_code == 422
    body = response.json()
    assert body["type"].endswith("/too-few-interests")
    assert "errors" not in body
    assert (await api.get_profile(token)).json()["onboarding_completed"] is False


async def test_an_account_already_done_finishes_again_without_interests(api):
    token = await signed_in(api)
    await set_user_flag(api.app, "onboarding_completed", True)

    assert (await complete_onboarding(api, token)).status_code == 204


async def test_completing_the_onboarding_requires_a_session(api):
    assert (await complete_onboarding(api, "token-invalido")).status_code == 401


async def test_the_accounts_that_already_existed_skip_the_onboarding(clean_state):
    config = Config("alembic.ini")
    await anyio.to_thread.run_sync(command.downgrade, config, BEFORE_ONBOARDING)
    try:
        engine = create_async_engine(os.environ["DATABASE_URL"])
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users (id, email, handle, password_hash, must_change_password, "
                    "is_email_verified, terms_accepted) VALUES "
                    "(:id, 'vieja@udesa.edu.ar', '@vieja', 'x', false, true, true)"
                ),
                {"id": uuid.uuid4()},
            )
        await engine.dispose()
    finally:
        await anyio.to_thread.run_sync(command.upgrade, config, "head")

    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as connection:
        existing = (
            await connection.execute(
                text("SELECT onboarding_completed, interests FROM users WHERE handle = '@vieja'")
            )
        ).one()
        await connection.execute(
            text(
                "INSERT INTO users (id, email, handle, password_hash, must_change_password, "
                "is_email_verified, terms_accepted) VALUES "
                "(:id, 'nueva@udesa.edu.ar', '@nueva', 'x', false, true, true)"
            ),
            {"id": uuid.uuid4()},
        )
        new = await connection.scalar(
            text("SELECT onboarding_completed FROM users WHERE handle = '@nueva'")
        )
    await engine.dispose()

    assert (existing.onboarding_completed, existing.interests) == (True, [])
    assert new is False
