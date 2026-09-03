"""Verification links, on PostgreSQL through SQLAlchemy."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from users_api.features.auth.domain import EmailVerificationToken
from users_api.features.auth.repositories import EmailVerificationTokenRepository
from users_api.infrastructure.database.models import EmailVerificationTokenModel


def to_domain(row: EmailVerificationTokenModel) -> EmailVerificationToken:
    return EmailVerificationToken(
        id=row.id,
        user_id=row.user_id,
        token_hash=row.token_hash,
        expires_at=row.expires_at,
        used_at=row.used_at,
    )


@dataclass
class SqlAlchemyEmailVerificationTokenRepository(EmailVerificationTokenRepository):
    session: AsyncSession

    async def add(self, token: EmailVerificationToken) -> None:
        self.session.add(
            EmailVerificationTokenModel(
                user_id=token.user_id,
                token_hash=token.token_hash,
                expires_at=token.expires_at,
            )
        )

    async def find_by_hash(self, token_hash: str) -> EmailVerificationToken | None:
        row = await self.session.scalar(
            select(EmailVerificationTokenModel).where(
                EmailVerificationTokenModel.token_hash == token_hash
            )
        )
        return to_domain(row) if row is not None else None

    async def mark_used(self, token_id: uuid.UUID, *, used_at: datetime) -> None:
        row = await self.session.get(EmailVerificationTokenModel, token_id)
        if row is not None:
            row.used_at = used_at
