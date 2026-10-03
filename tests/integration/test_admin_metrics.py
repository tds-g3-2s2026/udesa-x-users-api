"""The account numbers of the backoffice dashboard."""

import os

import pytest

from tests.integration.helpers import set_user_flag

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL"),
    reason="requires DATABASE_URL and REDIS_URL pointing at real services",
)


async def metrics(api, token: str):
    return await api.client.get("/admin/metrics", headers={"Authorization": f"Bearer {token}"})


async def test_counts_verified_app_accounts_by_status_and_leaves_administrators_out(api):
    # Registered first and promoted with a blanket UPDATE: only this account exists yet.
    await api.register_and_verify()
    await set_user_flag(api.app, "role", "moderator")
    token = (await api.admin_login()).json()["access_token"]

    await api.register_and_verify(email="activa@udesa.edu.ar", handle="@activa_01")
    reported = (await api.register(email="revision@udesa.edu.ar", handle="@revision_01")).json()
    await api.verify_last()
    await api.put_under_review(reported["id"], os.environ["INTERNAL_API_TOKEN"])
    # Never verified: it never got to use the platform.
    await api.register(email="pendiente@udesa.edu.ar", handle="@pendiente_01")

    response = await metrics(api, token)

    assert response.status_code == 200
    assert response.json() == {"active_users": 1, "accounts_under_review": 1}


async def test_an_app_account_cannot_read_the_metrics(api):
    await api.register_and_verify()
    token = (await api.login()).json()["access_token"]

    response = await metrics(api, token)

    assert response.status_code == 403
    assert response.json()["type"].endswith("administrator-required")
