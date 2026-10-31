from collections.abc import Awaitable, Callable

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from users_api.app.audit_events import AuditEvent, Outcome
from users_api.infrastructure.database.audit_repository import SqlAlchemyAuditLogRepository


def build_event_handler(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[bytes], Awaitable[Outcome]]:
    async def handle(body: bytes) -> Outcome:
        try:
            event = AuditEvent.model_validate_json(body)
        except ValidationError:
            return "reject"
        async with session_factory() as session, session.begin():
            await SqlAlchemyAuditLogRepository(session).add(event.entry())
        return "ack"

    return handle
