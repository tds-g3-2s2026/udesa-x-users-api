"""The refresh token repository against a real PostgreSQL.

What matters here is what a fake cannot prove: that consuming is a single
atomic statement, so two requests with the same token never both win, and that
revoking a family or an account reaches exactly the rows it should.
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from tests.integration.helpers import REGISTRATION
from users_api.app.models.tokens import RefreshToken
from users_api.infrastructure.database.refresh_token_repository import (
    SqlAlchemyRefreshTokenRepository,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL"),
    reason="requires DATABASE_URL and REDIS_URL pointing at real services",
)


async def registered_user_id(api, **overrides) -> uuid.UUID:
    assert (await api.register(**overrides)).status_code == 201
    email = overrides.get("email", REGISTRATION["email"]).lower()
    async with api.app.state.engine.begin() as connection:
        return await connection.scalar(
            text("SELECT id FROM users WHERE email = :email"), {"email": email}
        )


async def add_token(
    api,
    user_id: uuid.UUID,
    *,
    token_hash: str,
    family_id: uuid.UUID | None = None,
    expires_at: datetime | None = None,
) -> RefreshToken:
    token = RefreshToken(
        user_id=user_id,
        family_id=family_id or uuid.uuid4(),
        token_hash=token_hash,
        expires_at=expires_at or datetime.now(UTC) + timedelta(days=7),
    )
    async with api.app.state.session_factory() as session:
        await SqlAlchemyRefreshTokenRepository(session).add(token)
        await session.commit()
    return token


async def consume(api, token_hash: str) -> RefreshToken | None:
    async with api.app.state.session_factory() as session:
        consumed = await SqlAlchemyRefreshTokenRepository(session).consume(
            token_hash, now=datetime.now(UTC)
        )
        await session.commit()
    return consumed


async def find(api, token_hash: str) -> RefreshToken | None:
    async with api.app.state.session_factory() as session:
        return await SqlAlchemyRefreshTokenRepository(session).find_by_hash(token_hash)


async def test_a_token_is_consumed_once(api):
    user_id = await registered_user_id(api)
    added = await add_token(api, user_id, token_hash="a")

    consumed = await consume(api, "a")

    assert consumed is not None
    assert consumed.user_id == user_id
    assert consumed.family_id == added.family_id
    assert consumed.used_at is not None
    assert await consume(api, "a") is None


async def test_two_concurrent_consumptions_have_one_winner(api):
    user_id = await registered_user_id(api)
    await add_token(api, user_id, token_hash="race")

    results = await asyncio.gather(*(consume(api, "race") for _ in range(5)))

    assert sum(result is not None for result in results) == 1


async def test_an_expired_or_revoked_token_is_not_consumed(api):
    user_id = await registered_user_id(api)
    await add_token(
        api, user_id, token_hash="expired", expires_at=datetime.now(UTC) - timedelta(seconds=1)
    )
    revoked = await add_token(api, user_id, token_hash="revoked")
    async with api.app.state.session_factory() as session:
        await SqlAlchemyRefreshTokenRepository(session).revoke_family(
            revoked.family_id, revoked_at=datetime.now(UTC)
        )
        await session.commit()

    assert await consume(api, "expired") is None
    assert await consume(api, "revoked") is None
    # Refused, not erased: the row is still there to tell a reuse apart.
    assert (await find(api, "revoked")).revoked_at is not None


async def test_revoking_a_family_leaves_the_other_families_alone(api):
    user_id = await registered_user_id(api)
    family = uuid.uuid4()
    await add_token(api, user_id, token_hash="phone-1", family_id=family)
    await add_token(api, user_id, token_hash="phone-2", family_id=family)
    await add_token(api, user_id, token_hash="tablet")

    async with api.app.state.session_factory() as session:
        await SqlAlchemyRefreshTokenRepository(session).revoke_family(
            family, revoked_at=datetime.now(UTC)
        )
        await session.commit()

    assert (await find(api, "phone-1")).revoked_at is not None
    assert (await find(api, "phone-2")).revoked_at is not None
    assert (await find(api, "tablet")).revoked_at is None


async def test_revoking_an_account_leaves_other_accounts_alone(api):
    owner = await registered_user_id(api)
    other = await registered_user_id(api, email="otra@udesa.edu.ar", handle="@otra_cuenta")
    await add_token(api, owner, token_hash="owner-phone")
    await add_token(api, owner, token_hash="owner-tablet")
    await add_token(api, other, token_hash="other-phone")

    async with api.app.state.session_factory() as session:
        await SqlAlchemyRefreshTokenRepository(session).revoke_all(
            owner, revoked_at=datetime.now(UTC)
        )
        await session.commit()

    assert (await find(api, "owner-phone")).revoked_at is not None
    assert (await find(api, "owner-tablet")).revoked_at is not None
    assert (await find(api, "other-phone")).revoked_at is None
