"""Reading and editing one's own preferences.

Twin of `test_profile.py`: same authentication, different resource. What is
specific to this one is the enum-backed values and the defaults a new account
gets without ever touching the endpoint.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL"),
    reason="requires DATABASE_URL and REDIS_URL pointing at real services",
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
