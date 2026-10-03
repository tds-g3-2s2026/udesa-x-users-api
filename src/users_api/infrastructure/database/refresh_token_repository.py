"""Refresh tokens, on PostgreSQL through SQLAlchemy."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from users_api.app.models.tokens import RefreshToken
from users_api.app.repositories.tokens import RefreshTokenRepository
from users_api.infrastructure.database.models import RefreshTokenModel


def to_domain(row: RefreshTokenModel) -> RefreshToken:
    return RefreshToken(
        id=row.id,
        user_id=row.user_id,
        family_id=row.family_id,
        token_hash=row.token_hash,
        expires_at=row.expires_at,
        used_at=row.used_at,
        revoked_at=row.revoked_at,
    )


@dataclass
class SqlAlchemyRefreshTokenRepository(RefreshTokenRepository):
    session: AsyncSession

    async def add(self, token: RefreshToken) -> None:
        self.session.add(
            RefreshTokenModel(
                user_id=token.user_id,
                family_id=token.family_id,
                token_hash=token.token_hash,
                expires_at=token.expires_at,
            )
        )

    async def find_by_hash(self, token_hash: str) -> RefreshToken | None:
        row = await self.session.scalar(
            select(RefreshTokenModel).where(RefreshTokenModel.token_hash == token_hash)
        )
        return to_domain(row) if row is not None else None

    async def consume(self, token_hash: str, *, now: datetime) -> RefreshToken | None:
        # The conditions live in the UPDATE and not in a prior SELECT: PostgreSQL
        # takes the row lock here, so of two requests with the same token the
        # second waits, re-evaluates `used_at IS NULL` and matches nothing.
        row = await self.session.scalar(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.token_hash == token_hash,
                RefreshTokenModel.used_at.is_(None),
                RefreshTokenModel.revoked_at.is_(None),
                RefreshTokenModel.expires_at > now,
            )
            .values(used_at=now)
            .returning(RefreshTokenModel)
            .execution_options(synchronize_session=False)
        )
        return to_domain(row) if row is not None else None

    async def revoke_family(self, family_id: uuid.UUID, *, revoked_at: datetime) -> None:
        await self.session.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.family_id == family_id,
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )

    async def revoke_all(self, user_id: uuid.UUID, *, revoked_at: datetime) -> None:
        await self.session.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.user_id == user_id,
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )
