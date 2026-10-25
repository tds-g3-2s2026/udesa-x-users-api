"""The outbox, on PostgreSQL through SQLAlchemy."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from users_api.app.events import Event
from users_api.app.repositories.outbox import OutboxRepository
from users_api.infrastructure.database.models import OutboxModel


@dataclass
class SqlAlchemyOutboxRepository(OutboxRepository):
    session: AsyncSession

    async def add(self, event: Event) -> None:
        self.session.add(OutboxModel(id=event.id, type=event.type, payload=event.envelope))
