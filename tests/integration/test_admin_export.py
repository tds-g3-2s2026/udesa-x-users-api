"""Downloading the accounts a search finds as a CSV (E5-H8)."""

import csv
import io
import os
from datetime import timedelta

import pytest

from tests.integration.test_admin_user_accounts import NOW, administrator, given_account
from users_api.app.services import admin_user_accounts

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL"),
    reason="requires DATABASE_URL and REDIS_URL pointing at real services",
)


async def export(api, headers: dict[str, str], q: str):
    return await api.client.get("/admin/users/export.csv", params={"q": q}, headers=headers)


def rows(response) -> list[list[str]]:
    """The cells of the file, header included, after checking the BOM is there."""
    text = response.content.decode("utf-8")
    assert text.startswith("﻿")
    return list(csv.reader(io.StringIO(text[1:])))


async def test_e5_h8_ca1_the_csv_has_the_five_columns(api):
    headers = await administrator(api, role="superadmin")
    account = await given_account(api, "maria.gomez@udesa.edu.ar", "@mariag", status="suspended")

    response = await export(api, headers, "gomez")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="cuentas.csv"'
    assert rows(response) == [
        ["ID", "Handle", "Email", "Estado", "Fecha de registro"],
        # The handle starts with "@": a spreadsheet would read it as a formula.
        [account, "'@mariag", "maria.gomez@udesa.edu.ar", "Bloqueada", NOW.isoformat()],
    ]


async def test_e5_h8_ca1_the_csv_follows_the_search_filter(api, monkeypatch):
    # Pages of two, so three matches take two round trips.
    monkeypatch.setattr(admin_user_accounts, "EXPORT_PAGE_SIZE", 2)
    headers = await administrator(api, role="superadmin")
    oldest = await given_account(
        api, "a.gomez@udesa.edu.ar", "@agomez", created_at=NOW - timedelta(days=2)
    )
    middle = await given_account(
        api, "b.gomez@udesa.edu.ar", "@bgomez", created_at=NOW - timedelta(days=1)
    )
    newest = await given_account(api, "c.gomez@udesa.edu.ar", "@cgomez", created_at=NOW)
    await given_account(api, "otra@udesa.edu.ar", "@otra")
    await given_account(api, "borrada.gomez@udesa.edu.ar", "@bgomezz", deleted=True)
    await given_account(api, "admin.gomez@udesa.edu.ar", "@admingomez", role="moderator")

    response = await export(api, headers, "GOMEZ")

    # The same accounts as the search, in its order, and all of them at once.
    assert [row[0] for row in rows(response)[1:]] == [newest, middle, oldest]


async def test_e5_h8_ca2_a_moderator_gets_403(api):
    headers = await administrator(api, role="moderator")

    response = await export(api, headers, "gomez")

    assert response.status_code == 403
    assert response.json()["type"].endswith("/superadmin-required")


async def test_the_export_needs_three_characters_like_the_search(api):
    headers = await administrator(api, role="superadmin")

    response = await export(api, headers, "  ab  ")

    assert response.status_code == 422
    assert response.json()["type"].endswith("/search-query-too-short")


async def test_without_a_token_the_export_is_401(api):
    response = await api.client.get("/admin/users/export.csv", params={"q": "gomez"})

    assert response.status_code == 401


async def test_a_search_with_no_matches_still_gives_the_header(api):
    headers = await administrator(api, role="superadmin")

    response = await export(api, headers, "nadie")

    assert rows(response) == [["ID", "Handle", "Email", "Estado", "Fecha de registro"]]
