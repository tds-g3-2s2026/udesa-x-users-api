"""The inbox of comments and bug reports, from the backoffice."""

import uuid
from dataclasses import dataclass

from users_api.app.errors import ProblemError
from users_api.app.models.feedback import FeedbackStatus, InboxEntry
from users_api.app.repositories.feedback import FeedbackRepository

PAGE_SIZE = 20


@dataclass
class AdminFeedbackService:
    feedback: FeedbackRepository

    async def inbox(
        self, status: FeedbackStatus, *, cursor: str | None
    ) -> tuple[list[InboxEntry], str | None]:
        """The messages in `status`, newest first, twenty per page."""
        return await self.feedback.list_by_status(status, cursor=cursor, limit=PAGE_SIZE)

    async def mark_read(self, feedback_id: uuid.UUID) -> None:
        """Pending becomes read. A message already further on stays where it is."""
        await self.advance(
            feedback_id, to=FeedbackStatus.READ, from_any_of=frozenset({FeedbackStatus.PENDING})
        )

    async def resolve(self, feedback_id: uuid.UUID) -> None:
        """Pending or read becomes resolved, which takes it out of the inbox."""
        await self.advance(
            feedback_id,
            to=FeedbackStatus.RESOLVED,
            from_any_of=frozenset({FeedbackStatus.PENDING, FeedbackStatus.READ}),
        )

    async def advance(
        self,
        feedback_id: uuid.UUID,
        *,
        to: FeedbackStatus,
        from_any_of: frozenset[FeedbackStatus],
    ) -> None:
        """Asking twice is not an error: the second time there is nothing to do."""
        if not await self.feedback.advance(feedback_id, to=to, from_any_of=from_any_of):
            raise ProblemError(
                status=404,
                code="feedback-not-found",
                title="No se encontró el mensaje",
                detail="El mensaje no existe",
            )
