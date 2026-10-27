import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from users_api.app.errors import ProblemError
from users_api.app.models.audit import AuditEntry
from users_api.app.models.user import User
from users_api.app.repositories.audit import AuditLogRepository
from users_api.app.repositories.users import UserRepository


@dataclass
class AuditLog:
    entries: AuditLogRepository
    users: UserRepository

    async def administrator(self, actor_id: uuid.UUID) -> User:
        actor = await self.users.get(actor_id)
        if actor is None or not actor.is_administrator or actor.deleted_at is not None:
            raise ProblemError(
                status=404,
                code="administrator-not-found",
                title="No se encontró al administrador",
                detail="La cuenta no existe",
            )
        return actor

    async def record(
        self,
        actor_id: uuid.UUID,
        action: str,
        target_type: str,
        target_id: uuid.UUID,
        details: dict[str, Any],
    ) -> None:
        actor = await self.administrator(actor_id)
        await self.entries.add(
            AuditEntry(
                id=uuid.uuid4(),
                occurred_at=datetime.now(UTC),
                actor_id=actor.id,
                actor_email=actor.email,
                action=action,
                target_type=target_type,
                target_id=target_id,
                details=details,
            )
        )
