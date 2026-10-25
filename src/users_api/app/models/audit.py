import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AuditEntry:
    id: uuid.UUID
    occurred_at: datetime
    actor_id: uuid.UUID
    actor_email: str
    action: str
    target_type: str
    target_id: uuid.UUID
    details: dict[str, Any]
