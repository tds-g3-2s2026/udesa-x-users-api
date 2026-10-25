from dataclasses import asdict, dataclass

from sqlalchemy import func, select, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from users_api.app.models.audit import AuditEntry
from users_api.app.repositories.audit import AuditLogRepository
from users_api.infrastructure.database.models import AuditLogModel


@dataclass
class SqlAlchemyAuditLogRepository(AuditLogRepository):
    session: AsyncSession

    async def add(self, entry: AuditEntry) -> None:
        await self.session.execute(
            insert(AuditLogModel)
            .values(**asdict(entry))
            .on_conflict_do_nothing(index_elements=[AuditLogModel.id])
        )

    async def list_page(self, limit: int, offset: int) -> tuple[list[AuditEntry], int]:
        # One statement gives the total and page the same database snapshot.
        page = (
            select(AuditLogModel)
            .order_by(AuditLogModel.occurred_at.desc(), AuditLogModel.id.desc())
            .limit(limit)
            .offset(offset)
            .subquery()
        )
        total = select(func.count(AuditLogModel.id).label("total")).subquery()
        result = await self.session.execute(
            select(total.c.total, *page.c)
            .select_from(total.outerjoin(page, true()))
            .order_by(page.c.occurred_at.desc(), page.c.id.desc())
        )
        rows = result.mappings().all()
        return [
            AuditEntry(**{column.key: row[column.key] for column in page.c})
            for row in rows
            if row["id"] is not None
        ], rows[0]["total"]
