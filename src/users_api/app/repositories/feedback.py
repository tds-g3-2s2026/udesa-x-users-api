"""Where the messages users send from the app are kept."""

from abc import ABC, abstractmethod

from users_api.app.models.feedback import Feedback


class FeedbackRepository(ABC):
    @abstractmethod
    async def add(self, feedback: Feedback) -> None:
        """Store the message inside the transaction of the request."""
