"""Where the messages users send from the app are kept."""

import uuid
from abc import ABC, abstractmethod

from users_api.app.models.feedback import Feedback, FeedbackStatus, InboxEntry


class FeedbackRepository(ABC):
    @abstractmethod
    async def add(self, feedback: Feedback) -> None:
        """Store the message inside the transaction of the request."""

    @abstractmethod
    async def list_by_status(
        self, status: FeedbackStatus, *, cursor: str | None, limit: int
    ) -> tuple[list[InboxEntry], str | None]:
        """The messages in `status`, newest first, and the cursor of the next page."""

    @abstractmethod
    async def advance(
        self,
        feedback_id: uuid.UUID,
        *,
        to: FeedbackStatus,
        from_any_of: frozenset[FeedbackStatus],
    ) -> bool:
        """Move the message to `to` if it stands in one of `from_any_of`.

        A message elsewhere is left as it is. False only when it does not exist.
        """
