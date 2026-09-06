"""Reading and editing one's own profile.

`GET /me` and `PATCH /me` are the first pair of endpoints in the service that
only make sense to call while authenticated, so a good part of what gets
tested here is that authentication itself, not only the profile.
"""

import os

import pytest

from tests.integration.helpers import REGISTRATION

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL"),
    reason="requires DATABASE_URL and REDIS_URL pointing at real services",
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
