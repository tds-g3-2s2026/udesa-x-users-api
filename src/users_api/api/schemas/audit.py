import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    occurred_at: datetime
    actor_id: uuid.UUID
    actor_email: str
    action: str
    target_type: str
    target_id: uuid.UUID
    details: dict[str, Any]


class AuditPage(BaseModel):
    items: list[AuditEntryResponse]
    total: int


class AdministratorIdentity(BaseModel):
    id: uuid.UUID
    email: str
