"""The account numbers of the backoffice dashboard."""

import os
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from tests.integration.helpers import set_user_flag

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL") or not os.getenv("RABBITMQ_URL"),
    reason="requires DATABASE_URL, REDIS_URL and RABBITMQ_URL pointing at real services",
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


async def registrations(api, token: str, since: datetime):
    return await api.client.get(
        "/admin/metrics/registrations",
        params={"since": since.isoformat()},
        headers={"Authorization": f"Bearer {token}"},
    )


async def set_created_at(api, email: str, when: datetime) -> None:
    async with api.app.state.engine.begin() as connection:
        await connection.execute(
            text("UPDATE users SET created_at = :when WHERE email = :email"),
            {"when": when, "email": email},
        )


async def sign_in_as_administrator(api) -> str:
    # Registered first and promoted with a blanket UPDATE: only this account exists yet.
    await api.register_and_verify()
    await set_user_flag(api.app, "role", "moderator")
    return (await api.admin_login()).json()["access_token"]


def start_of_the_week(offset: timezone = UTC) -> datetime:
    """Midnight, in `offset`, of the day six days ago: where the dashboard's week starts."""
    return (datetime.now(offset) - timedelta(days=6)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def days_from(since: datetime, count: int = 7) -> list[str]:
    return [(since + timedelta(days=position)).date().isoformat() for position in range(count)]


async def test_e5_h3_ca2_counts_registrations_per_day_of_the_last_week(api):
    token = await sign_in_as_administrator(api)
    since = start_of_the_week(timezone(timedelta(hours=-3)))
    created = {
        "primera@udesa.edu.ar": since + timedelta(hours=3),
        "segunda@udesa.edu.ar": since + timedelta(hours=23, minutes=59),
        "tercera@udesa.edu.ar": since + timedelta(days=2, hours=1),
    }
    for number, (email, when) in enumerate(created.items()):
        await api.register_and_verify(email=email, handle=f"@cuenta_0{number}")
        await set_created_at(api, email, when)
    # Never verified and created just now: a registration all the same, in the last day.
    await api.register(email="reciente@udesa.edu.ar", handle="@reciente_01")

    response = await registrations(api, token, since)

    assert response.status_code == 200
    assert response.json() == {
        "days": [
            {"date": date, "registrations": count}
            for date, count in zip(days_from(since), [2, 0, 1, 0, 0, 0, 1], strict=True)
        ]
    }


async def test_e5_h3_ca2_a_day_without_registrations_counts_zero(api):
    token = await sign_in_as_administrator(api)
    since = start_of_the_week()
    await api.register_and_verify(email="unica@udesa.edu.ar", handle="@unica_01")
    await set_created_at(api, "unica@udesa.edu.ar", since + timedelta(days=4, hours=12))

    response = await registrations(api, token, since)

    assert response.status_code == 200
    days = response.json()["days"]
    # The administrator is not an app account, so the other six days are empty and listed.
    assert [day["date"] for day in days] == days_from(since)
    assert [day["registrations"] for day in days] == [0, 0, 0, 0, 1, 0, 0]


async def test_the_day_starts_where_the_one_who_asks_says(api):
    token = await sign_in_as_administrator(api)
    since_utc = start_of_the_week()
    await api.register_and_verify(email="madrugada@udesa.edu.ar", handle="@madrugada_1")
    # 02:00 UTC is still the day before in Buenos Aires, which is three hours behind.
    await set_created_at(api, "madrugada@udesa.edu.ar", since_utc + timedelta(hours=2))
    since_buenos_aires = (since_utc + timedelta(hours=3)).astimezone(timezone(timedelta(hours=-3)))

    in_utc = (await registrations(api, token, since_utc)).json()["days"]
    in_buenos_aires = (await registrations(api, token, since_buenos_aires)).json()["days"]

    assert in_utc[0] == {"date": since_utc.date().isoformat(), "registrations": 1}
    # For the one who asks from Buenos Aires the account predates the week.
    assert sum(day["registrations"] for day in in_buenos_aires) == 0


async def test_a_since_in_the_future_has_no_days(api):
    token = await sign_in_as_administrator(api)

    response = await registrations(api, token, datetime.now(UTC) + timedelta(days=2))

    assert response.status_code == 200
    assert response.json() == {"days": []}


async def test_a_period_longer_than_the_limit_is_refused(api):
    token = await sign_in_as_administrator(api)

    response = await registrations(api, token, datetime.now(UTC) - timedelta(days=400))

    assert response.status_code == 422
    assert response.json()["type"].endswith("metrics-range-too-long")


async def test_a_moment_without_offset_is_refused(api):
    token = await sign_in_as_administrator(api)

    response = await api.client.get(
        "/admin/metrics/registrations",
        params={"since": "2026-11-09T00:00:00"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422


async def test_an_app_account_cannot_read_the_registrations(api):
    await api.register_and_verify()
    token = (await api.login()).json()["access_token"]

    response = await registrations(api, token, start_of_the_week())

    assert response.status_code == 403
    assert response.json()["type"].endswith("administrator-required")
