"""An administrator clearing the biography of an app account (E5-H10)."""

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from tests.integration.test_admin_block import (
    MODERATOR,
    OTHER_USER,
    SUPERADMIN,
    administrator,
    administrator_with_id,
    detail,
    given_registered,
    set_columns,
)
from tests.integration.test_internal_profile import internal_token
from users_api.infrastructure.database.models import AuditLogModel

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL"),
    reason="requires DATABASE_URL and REDIS_URL pointing at real services",
)

PLACEHOLDER = "[Contenido eliminado por moderación]"
BIO = "Vendo seguidores, escribime por privado"


async def account_with_bio(api, **profile) -> tuple[str, str]:
    """A verified account with its profile filled in, and an access token for it."""
    user_id = await given_registered(api)
    token = (await api.login()).json()["access_token"]
    assert (await api.update_profile(token, **(profile or {"bio": BIO}))).status_code == 200
    return user_id, token


async def clean(api, headers: dict[str, str], user_id: str):
    return await api.client.post(f"/admin/users/{user_id}/clean-content", headers=headers)


async def audit_entries(api, user_id: str) -> list[AuditLogModel]:
    async with api.app.state.session_factory() as session:
        found = await session.scalars(
            select(AuditLogModel).where(AuditLogModel.target_id == uuid.UUID(user_id))
        )
        return list(found)


async def test_e5_h10_ca2_the_bio_is_replaced_by_the_placeholder(api):
    headers = await administrator(api, MODERATOR, "moderator")
    user_id, _ = await account_with_bio(api)
    assert (await detail(api, headers, user_id))["bio"] == BIO

    response = await clean(api, headers, user_id)

    assert response.status_code == 204
    assert (await detail(api, headers, user_id))["bio"] == PLACEHOLDER
    # posts-api asks for the profile each time one opens, so the next visit shows it.
    profile = (await api.get_public_profile(user_id, internal_token())).json()
    assert profile["bio"] == PLACEHOLDER


async def test_e5_h10_the_name_and_the_sessions_stay(api):
    headers = await administrator(api, MODERATOR, "moderator")
    user_id, token = await account_with_bio(api, display_name="Ana Pérez", bio=BIO)

    assert (await clean(api, headers, user_id)).status_code == 204

    body = await detail(api, headers, user_id)
    assert (body["display_name"], body["status"]) == ("Ana Pérez", "active")
    # Unlike a block, the owner keeps using the app.
    assert (await api.get_profile(token)).status_code == 200


async def test_e5_h10_cleaning_leaves_an_audit_entry(api):
    moderator_id, headers = await administrator_with_id(api, MODERATOR, "moderator")
    user_id, _ = await account_with_bio(api)

    await clean(api, headers, user_id)

    [entry] = await audit_entries(api, user_id)
    assert (entry.actor_id, entry.actor_email) == (uuid.UUID(moderator_id), MODERATOR["email"])
    assert (entry.action, entry.target_type) == ("user.content_cleaned", "user")
    assert entry.details == {"fields": ["bio"]}


async def test_e5_h10_cleaning_twice_audits_it_once(api):
    first = await administrator(api, MODERATOR, "moderator")
    second = await administrator(api, SUPERADMIN, "superadmin")
    user_id, _ = await account_with_bio(api)

    assert (await clean(api, first, user_id)).status_code == 204
    assert (await clean(api, second, user_id)).status_code == 204

    assert (await detail(api, first, user_id))["bio"] == PLACEHOLDER
    assert len(await audit_entries(api, user_id)) == 1


async def test_e5_h10_an_empty_bio_stays_empty(api):
    headers = await administrator(api, MODERATOR, "moderator")
    user_id = await given_registered(api)

    assert (await clean(api, headers, user_id)).status_code == 204

    assert (await detail(api, headers, user_id))["bio"] is None
    assert await audit_entries(api, user_id) == []


@pytest.mark.parametrize("account", ["unknown", "deleted", "administrator"])
async def test_e5_h10_only_an_app_account_can_be_cleaned(api, account):
    headers = await administrator(api, MODERATOR, "moderator")
    user_id = str(uuid.uuid4())
    if account == "deleted":
        user_id = await given_registered(api)
        await set_columns(api, user_id, deleted_at=datetime.now(UTC))
    if account == "administrator":
        user_id = await given_registered(api, **SUPERADMIN)
        await set_columns(api, user_id, role="superadmin")

    response = await clean(api, headers, user_id)

    assert response.status_code == 404
    assert response.json()["type"].endswith("/account-not-found")


async def test_e5_h10_an_app_user_cannot_clean(api):
    target_id = await given_registered(api, **OTHER_USER)
    await given_registered(api)
    token = (await api.login()).json()["access_token"]

    response = await clean(api, {"Authorization": f"Bearer {token}"}, target_id)

    assert response.status_code == 403
    assert response.json()["type"].endswith("/administrator-required")
