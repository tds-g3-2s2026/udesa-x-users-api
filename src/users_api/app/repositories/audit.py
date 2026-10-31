from abc import ABC, abstractmethod

from users_api.app.models.audit import AuditEntry, AuditEntryWithTarget


class AuditLogRepository(ABC):
    @abstractmethod
    async def add(self, entry: AuditEntry) -> None: ...

    @abstractmethod
    async def list_page(
        self, limit: int, offset: int
    ) -> tuple[list[AuditEntryWithTarget], int]: ...
