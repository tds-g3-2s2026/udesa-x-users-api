"""Recovery links, on PostgreSQL through SQLAlchemy."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from users_api.app.models.tokens import PasswordResetToken
from users_api.app.repositories.tokens import PasswordResetTokenRepository
from users_api.infrastructure.database.models import PasswordResetTokenModel


def to_domain(row: PasswordResetTokenModel) -> PasswordResetToken:
    return PasswordResetToken(
        id=row.id,
        user_id=row.user_id,
        token_hash=row.token_hash,
        expires_at=row.expires_at,
        used_at=row.used_at,
    )


@dataclass
class SqlAlchemyPasswordResetTokenRepository(PasswordResetTokenRepository):
    session: AsyncSession

    async def add(self, token: PasswordResetToken) -> None:
        self.session.add(
            PasswordResetTokenModel(
                user_id=token.user_id,
                token_hash=token.token_hash,
                expires_at=token.expires_at,
            )
        )

    async def find_by_hash(self, token_hash: str) -> PasswordResetToken | None:
        row = await self.session.scalar(
            select(PasswordResetTokenModel).where(PasswordResetTokenModel.token_hash == token_hash)
        )
        return to_domain(row) if row is not None else None

    async def mark_all_used(self, user_id: uuid.UUID, *, used_at: datetime) -> None:
        await self.session.execute(
            update(PasswordResetTokenModel)
            .where(
                PasswordResetTokenModel.user_id == user_id,
                PasswordResetTokenModel.used_at.is_(None),
            )
            .values(used_at=used_at)
        )
