"""The public profile posts-api reads to show another user's profile (E2-H14)."""

import os
import uuid
from datetime import UTC, datetime

import pytest

from tests.integration.helpers import set_user_flag

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL") or not os.getenv("RABBITMQ_URL"),
    reason="requires DATABASE_URL, REDIS_URL and RABBITMQ_URL pointing at real services",
)


def internal_token() -> str:
    # Read and not hardcoded: CI sets its own value.
    return os.environ["INTERNAL_API_TOKEN"]


async def signed_up(api) -> tuple[str, str]:
    """A verified account and an access token for it."""
    user_id = (await api.register()).json()["id"]
    await api.verify_last()
    token = (await api.login()).json()["access_token"]
    return user_id, token


async def test_e2_h14_ca1_the_profile_carries_name_bio_and_registration_date(api):
    user_id, token = await signed_up(api)
    await api.update_profile(token, display_name="Ana Pérez", bio="Estudio en la UdeSA")
    own = (await api.get_profile(token)).json()

    response = await api.get_public_profile(user_id, internal_token())

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == user_id
    assert body["handle"] == own["handle"]
    assert body["display_name"] == "Ana Pérez"
    assert body["bio"] == "Estudio en la UdeSA"
    assert datetime.fromisoformat(body["created_at"]) <= datetime.now(UTC)


async def test_e2_h14_ca1_a_profile_never_filled_in_comes_back_empty(api):
    user_id, _ = await signed_up(api)

    body = (await api.get_public_profile(user_id, internal_token())).json()

    assert body["display_name"] is None
    assert body["bio"] is None


async def test_the_public_profile_never_carries_the_email(api):
    user_id, _ = await signed_up(api)

    body = (await api.get_public_profile(user_id, internal_token())).json()

    assert "email" not in body


@pytest.mark.parametrize("visibility", ["public", "protected"])
async def test_e2_h10_ca6_internal_profile_includes_current_visibility(api, visibility):
    user_id, _ = await signed_up(api)
    await set_user_flag(api.app, "profile_visibility", visibility)

    response = await api.get_public_profile(user_id, internal_token())

    assert response.status_code == 200
    assert response.json()["profile_visibility"] == visibility
    assert not {"email", "password_hash", "access_token"} & response.json().keys()


async def test_an_unknown_account_is_404(api):
    response = await api.get_public_profile(str(uuid.uuid4()), internal_token())

    assert response.status_code == 404
    assert response.json()["type"].endswith("/account-not-found")


async def test_a_deleted_account_is_404_like_an_unknown_one(api):
    user_id, _ = await signed_up(api)
    await set_user_flag(api.app, "deleted_at", datetime.now(UTC))

    response = await api.get_public_profile(user_id, internal_token())

    assert response.status_code == 404
    assert response.json()["type"].endswith("/account-not-found")


async def test_the_route_asks_for_the_internal_token(api):
    user_id, _ = await signed_up(api)

    missing = await api.get_public_profile(user_id)
    wrong = await api.get_public_profile(user_id, "not-the-token")

    for response in (missing, wrong):
        assert response.status_code == 401
        assert response.json()["type"].endswith("/invalid-internal-token")
