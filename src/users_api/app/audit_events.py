import uuid
from typing import Literal

from pydantic import AwareDatetime, BaseModel, EmailStr, Field

from users_api.app.models.audit import AuditEntry

ADMIN_ACTION_RECORDED = "admin.action_recorded.v1"
Outcome = Literal["ack", "reject"]


class AuditDetails(BaseModel):
    reports_count: int = Field(ge=1, strict=True)


class AuditData(BaseModel):
    actor_id: uuid.UUID
    actor_email: EmailStr
    action: Literal["report.dismissed", "report.resolved"]
    target_type: Literal["user"]
    target_id: uuid.UUID
    details: AuditDetails


class AuditEvent(BaseModel):
    specversion: Literal["1.0"]
    id: uuid.UUID
    source: Literal["posts-api"]
    type: Literal["admin.action_recorded.v1"]
    time: AwareDatetime
    data: AuditData

    def entry(self) -> AuditEntry:
        return AuditEntry(
            id=self.id,
            occurred_at=self.time,
            actor_id=self.data.actor_id,
            actor_email=str(self.data.actor_email),
            action=self.data.action,
            target_type=self.data.target_type,
            target_id=self.data.target_id,
            details=self.data.details.model_dump(),
        )
