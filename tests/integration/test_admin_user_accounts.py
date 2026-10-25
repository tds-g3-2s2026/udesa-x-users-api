"""Searching app accounts and reading their detail from the backoffice (E5-H4)."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert

from tests.integration.helpers import set_user_flag
from users_api.infrastructure.database.models import UserModel

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL"),
    reason="requires DATABASE_URL and REDIS_URL pointing at real services",
)

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


async def administrator(api, role: str = "moderator") -> dict[str, str]:
    """The registered account, promoted, and the headers of its backoffice session.

    Promoted before any other account exists: `set_user_flag` updates every row.
    """
    await api.register_and_verify()
    await set_user_flag(api.app, "role", role)
    token = (await api.admin_login()).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def given_account(
    api,
    email: str,
    handle: str,
    *,
    created_at: datetime = NOW,
    role: str = "user",
    status: str = "active",
    deleted: bool = False,
) -> str:
    """An account straight into the table, with its creation date under control."""
    account_id = uuid.uuid4()
    async with api.app.state.engine.begin() as connection:
        await connection.execute(
            insert(UserModel).values(
                id=account_id,
                email=email,
                handle=handle,
                password_hash="not-a-real-hash",
                is_email_verified=True,
                role=role,
                status=status,
                deleted_at=NOW if deleted else None,
                created_at=created_at,
            )
        )
    return str(account_id)


async def search(api, headers: dict[str, str], q: str, cursor: str | None = None):
    params = {"q": q} if cursor is None else {"q": q, "cursor": cursor}
    return await api.client.get("/admin/users/search", params=params, headers=headers)


async def test_e5_h4_ca1_detail_shows_status_and_registration_date(api):
    headers = await administrator(api)
    account = await given_account(
        api, "denunciada@udesa.edu.ar", "@denunciada", status="under_review"
    )

    response = await api.client.get(f"/admin/users/{account}", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == account
    assert body["email"] == "denunciada@udesa.edu.ar"
    assert body["handle"] == "@denunciada"
    assert body["status"] == "under_review"
    assert datetime.fromisoformat(body["created_at"]) == NOW
    assert body["is_email_verified"] is True
    assert "password_hash" not in body


async def test_e5_h4_ca2_search_matches_part_of_email_or_handle(api):
    headers = await administrator(api)
    by_email = await given_account(api, "maria.gomez@udesa.edu.ar", "@mariag")
    by_handle = await given_account(api, "otra@gmail.com", "@gomezito")
    await given_account(api, "juan@udesa.edu.ar", "@juanpe")

    lower = (await search(api, headers, "gomez")).json()
    upper = (await search(api, headers, "GOMEZ")).json()

    assert {one["id"] for one in lower["items"]} == {by_email, by_handle}
    assert {one["id"] for one in upper["items"]} == {by_email, by_handle}


async def test_e5_h4_ca2_wildcards_in_the_query_match_literally(api):
    headers = await administrator(api)
    literal = await given_account(api, "a_b_c@udesa.edu.ar", "@abc_uno")
    await given_account(api, "axbxc@udesa.edu.ar", "@abc_dos")

    underscore = (await search(api, headers, "a_b")).json()
    percent = (await search(api, headers, "%%%")).json()

    assert [one["id"] for one in underscore["items"]] == [literal]
    assert percent["items"] == []


async def test_e5_h4_ca3_search_is_paginated_newest_first(api):
    headers = await administrator(api)
    for index in range(25):
        await given_account(
            api,
            f"pagina{index:02}@udesa.edu.ar",
            f"@pag_{index:02}",
            created_at=NOW + timedelta(minutes=index),
        )

    first = (await search(api, headers, "pagina")).json()
    second = (await search(api, headers, "pagina", first["next_cursor"])).json()

    assert [one["handle"] for one in first["items"]] == [
        f"@pag_{index:02}" for index in range(24, 4, -1)
    ]
    assert first["next_cursor"] is not None
    assert [one["handle"] for one in second["items"]] == [
        f"@pag_{index:02}" for index in range(4, -1, -1)
    ]
    assert second["next_cursor"] is None


async def test_e5_h4_a_user_token_cannot_search(api):
    await api.register_and_verify()
    token = (await api.login()).json()["access_token"]

    response = await search(api, {"Authorization": f"Bearer {token}"}, "alumno")

    assert response.status_code == 403
    assert response.json()["type"].endswith("/administrator-required")


async def test_a_superadmin_can_search_too(api):
    headers = await administrator(api, role="superadmin")
    await given_account(api, "cualquiera@udesa.edu.ar", "@cualquiera")

    response = await search(api, headers, "cualquiera")

    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


async def test_without_a_token_the_search_is_401(api):
    response = await api.client.get("/admin/users/search", params={"q": "alumno"})

    assert response.status_code == 401


async def test_the_search_needs_three_characters(api):
    headers = await administrator(api)

    for query in ("ab", "   ab   "):
        response = await search(api, headers, query)
        assert response.status_code == 422
        assert response.json()["type"].endswith("/search-query-too-short")


async def test_deleted_and_administrator_accounts_stay_out(api):
    headers = await administrator(api)
    deleted = await given_account(api, "borrada@udesa.edu.ar", "@borrada", deleted=True)
    admin = await given_account(api, "otro.admin@udesa.edu.ar", "@otroadmin", role="moderator")
    live = await given_account(api, "viva@udesa.edu.ar", "@viva")

    found = (await search(api, headers, "udesa.edu.ar")).json()

    assert [one["id"] for one in found["items"]] == [live]
    for hidden in (deleted, admin):
        detail = await api.client.get(f"/admin/users/{hidden}", headers=headers)
        assert detail.status_code == 404
        assert detail.json()["type"].endswith("/account-not-found")


async def test_an_unknown_account_is_404(api):
    headers = await administrator(api)

    response = await api.client.get(f"/admin/users/{uuid.uuid4()}", headers=headers)

    assert response.status_code == 404


async def test_a_tampered_cursor_is_400(api):
    headers = await administrator(api)

    response = await search(api, headers, "alumno", cursor="no-es-un-cursor")

    assert response.status_code == 400
    assert response.json()["type"].endswith("/invalid-cursor")
