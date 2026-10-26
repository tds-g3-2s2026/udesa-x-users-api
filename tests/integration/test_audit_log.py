import os
import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from tests.integration.test_admin_block import (
    MODERATOR,
    SUPERADMIN,
    administrator_with_id,
    block,
    given_registered,
    set_columns,
)
from users_api.app.models.audit import AuditEntry
from users_api.infrastructure.database.audit_repository import SqlAlchemyAuditLogRepository
from users_api.infrastructure.database.models import UserModel

pytestmark = pytest.mark.skipif(
    not all(os.getenv(key) for key in ("DATABASE_URL", "REDIS_URL", "RABBITMQ_URL")),
    reason="requires PostgreSQL, Redis and RabbitMQ",
)


async def entries(api, headers, **params):
    return await api.client.get("/admin/audit", headers=headers, params=params)


async def test_e5_h6_ca1_creation_and_reset_preserve_actor_email_without_credentials(api):
    actor_id, headers = await administrator_with_id(api, SUPERADMIN, "superadmin")
    created = await api.client.post(
        "/admin/users",
        headers=headers,
        json={
            **MODERATOR,
            "role": "moderator",
        },
    )
    assert created.status_code == 201
    target = created.json()["id"]
    reset = await api.client.post(
        f"/admin/users/{target}/reset-temporary-password", headers=headers
    )
    assert reset.status_code == 200
    await set_columns(api, actor_id, email="changed@udesa.edu.ar")
    response = await entries(api, headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [e["action"] for e in body["items"]] == [
        "admin.temporary_password_reset",
        "admin.created",
    ]
    for entry in body["items"]:
        assert entry["actor_id"] == actor_id
        assert entry["actor_email"] == SUPERADMIN["email"]
        assert entry["target_id"] == target
        assert entry["target_handle"] == MODERATOR["handle"]
        assert datetime.fromisoformat(entry["occurred_at"]).tzinfo is not None
        assert created.json()["temporary_password"] not in str(entry)
        assert reset.json()["temporary_password"] not in str(entry)
    assert body["items"][0]["details"] == {}
    assert body["items"][1]["details"] == {"email": MODERATOR["email"]}


async def test_e5_h6_ca1_blocking_twice_records_only_the_effective_action(api):
    _, headers = await administrator_with_id(api, MODERATOR, "moderator")
    target = await given_registered(api)
    assert (await block(api, headers, target)).status_code == 204
    assert (await block(api, headers, target)).status_code == 204
    assert (await entries(api, headers)).json()["total"] == 1


async def test_audit_reads_the_current_handle_without_changing_the_stored_entry(api):
    _, headers = await administrator_with_id(api, MODERATOR, "moderator")
    target = await given_registered(api)
    await block(api, headers, target)
    original = (await entries(api, headers)).json()["items"][0]
    await set_columns(api, target, handle="@renamed_user")

    current = (await entries(api, headers)).json()["items"][0]

    assert current["target_handle"] == "@renamed_user"
    assert {**current, "target_handle": original["target_handle"]} == original
    async with api.app.state.session_factory() as session:
        assert await session.scalar(text("SELECT count(*) FROM admin_audit_log")) == 1


async def test_deleted_accounts_keep_the_audit_entry_without_a_display_handle(api):
    _, headers = await administrator_with_id(api, MODERATOR, "moderator")
    target = await given_registered(api)
    await block(api, headers, target)
    original = (await entries(api, headers)).json()["items"][0]
    await set_columns(api, target, deleted_at=datetime.now(UTC))

    page = (await entries(api, headers)).json()

    assert page["total"] == 1
    assert page["items"] == [{**original, "target_handle": None}]


async def test_handles_are_only_resolved_for_user_targets(api):
    actor_id, headers = await administrator_with_id(api, MODERATOR, "moderator")
    async with api.app.state.session_factory() as session, session.begin():
        await SqlAlchemyAuditLogRepository(session).add(
            AuditEntry(
                uuid.uuid4(),
                datetime.now(UTC),
                uuid.UUID(actor_id),
                MODERATOR["email"],
                "report.resolved",
                "post",
                uuid.UUID(actor_id),
                {},
            )
        )

    [entry] = (await entries(api, headers)).json()["items"]

    assert entry["target_handle"] is None


async def test_e5_h6_ca1_failed_audit_rolls_back_administrator_creation(api, monkeypatch):
    _, headers = await administrator_with_id(api, SUPERADMIN, "superadmin")
    from users_api.app.errors import ProblemError

    original = SqlAlchemyAuditLogRepository.add

    async def fail(self, entry):
        await original(self, entry)
        raise ProblemError(status=503, code="unavailable", title="Error", detail="Error")

    monkeypatch.setattr(SqlAlchemyAuditLogRepository, "add", fail)
    response = await api.client.post(
        "/admin/users",
        headers=headers,
        json={
            **MODERATOR,
            "role": "moderator",
        },
    )
    assert response.status_code == 503
    assert (await entries(api, headers)).json()["total"] == 0
    async with api.app.state.session_factory() as session:
        assert (
            await session.scalar(select(UserModel).where(UserModel.email == MODERATOR["email"]))
            is None
        )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE admin_audit_log SET action = 'report.resolved'",
        "DELETE FROM admin_audit_log",
        "TRUNCATE admin_audit_log",
    ],
)
async def test_e5_h6_ca2_database_refuses_modification_even_for_table_owner(api, statement):
    _, headers = await administrator_with_id(api, MODERATOR, "moderator")
    target = await given_registered(api)
    await block(api, headers, target)
    with pytest.raises(DBAPIError, match="immutable"):
        async with api.app.state.engine.begin() as connection:
            await connection.execute(text(statement))
    assert (await entries(api, headers)).json()["total"] == 1


async def test_e5_h6_ca2_no_public_write_routes_and_regular_users_are_refused(api):
    await api.register_and_verify()
    token = (await api.login()).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert (await entries(api, headers)).status_code == 403
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        response = await api.client.request(method, "/admin/audit", headers=headers)
        assert response.status_code == 405
    assert (await api.client.get("/admin/audit")).status_code in (401, 403)


@pytest.mark.parametrize("role", ["superadmin", "moderator"])
async def test_e5_h6_ca3_both_admin_roles_can_read_stable_pages_and_totals(api, role):
    actor_id, headers = await administrator_with_id(api, SUPERADMIN, role)
    instant = datetime.now(UTC)
    ids = [uuid.UUID(int=i) for i in range(1, 4)]
    async with api.app.state.session_factory() as session, session.begin():
        repo = SqlAlchemyAuditLogRepository(session)
        for key in ids:
            entry = AuditEntry(
                key,
                instant,
                uuid.UUID(actor_id),
                SUPERADMIN["email"],
                "report.resolved",
                "user",
                uuid.uuid4(),
                {"reports_count": 1},
            )
            await repo.add(entry)
            await repo.add(replace(entry))
    first = (await entries(api, headers, limit=2)).json()
    second = (await entries(api, headers, limit=2, offset=2)).json()
    assert first["total"] == second["total"] == 3
    assert all(entry["target_handle"] is None for entry in first["items"] + second["items"])
    assert [e["id"] for e in first["items"] + second["items"]] == [str(i) for i in reversed(ids)]
    assert (await entries(api, headers, offset=99)).json() == {"items": [], "total": 3}
    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        assert (await entries(api, headers, **params)).status_code == 422


async def test_e5_h6_internal_identity_requires_token_and_administrator(api):
    actor_id, _ = await administrator_with_id(api, MODERATOR, "moderator")
    url = f"http://test/internal/administrators/{actor_id}/identity"
    assert (await api.client.get(url)).status_code == 401
    assert (await api.client.get(url, headers={"X-Internal-Token": "wrong"})).status_code == 401
    headers = {"X-Internal-Token": os.environ["INTERNAL_API_TOKEN"]}
    assert (await api.client.get(url, headers=headers)).json() == {
        "id": actor_id,
        "email": MODERATOR["email"],
    }
    target = await given_registered(api)
    assert (
        await api.client.get(
            f"http://test/internal/administrators/{target}/identity", headers=headers
        )
    ).status_code == 404
    await set_columns(api, actor_id, deleted_at=datetime.now(UTC))
    assert (await api.client.get(url, headers=headers)).status_code == 404
