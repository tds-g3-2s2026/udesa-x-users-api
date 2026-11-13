import uuid
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, EmailStr, Field

from users_api.app.models.audit import AuditEntry

ADMIN_ACTION_RECORDED = "admin.action_recorded.v1"
Outcome = Literal["ack", "reject"]


class ReportDetails(BaseModel):
    reports_count: int = Field(ge=1, strict=True)


class CleanedPostDetails(BaseModel):
    author_id: uuid.UUID


class ReportDecision(BaseModel):
    """An administrator closing the reports of an account (E5-H7)."""

    actor_id: uuid.UUID
    actor_email: EmailStr
    action: Literal["report.dismissed", "report.resolved"]
    target_type: Literal["user"]
    target_id: uuid.UUID
    details: ReportDetails


class CleanedPost(BaseModel):
    """An administrator replacing the text of a post with the placeholder (E5-H10)."""

    actor_id: uuid.UUID
    actor_email: EmailStr
    action: Literal["post.content_cleaned"]
    target_type: Literal["post"]
    target_id: uuid.UUID
    details: CleanedPostDetails


class AuditEvent(BaseModel):
    specversion: Literal["1.0"]
    id: uuid.UUID
    source: Literal["posts-api"]
    type: Literal["admin.action_recorded.v1"]
    time: AwareDatetime
    # The action decides the target and the details, the same rule as the contract.
    data: Annotated[ReportDecision | CleanedPost, Field(discriminator="action")]

    def entry(self) -> AuditEntry:
        return AuditEntry(
            id=self.id,
            occurred_at=self.time,
            actor_id=self.data.actor_id,
            actor_email=str(self.data.actor_email),
            action=self.data.action,
            target_type=self.data.target_type,
            target_id=self.data.target_id,
            details=self.data.details.model_dump(mode="json"),
        )
