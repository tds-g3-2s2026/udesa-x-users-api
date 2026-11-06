"""Comments and bug reports sent from the app."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from users_api.app import events
from users_api.app.errors import ProblemError
from users_api.app.models.feedback import Feedback
from users_api.app.models.user import User
from users_api.app.repositories.feedback import FeedbackRepository
from users_api.app.repositories.outbox import OutboxRepository
from users_api.app.repositories.rate_limiter import RateLimiter

# Not settings: every message ends up in the support mailbox, and this cap is
# what keeps one account from filling it.
MAX_MESSAGES = 2
WINDOW_MINUTES = 60


def feedback_limit_key(user_id: uuid.UUID) -> str:
    return f"feedback:sent:{user_id}"


@dataclass
class FeedbackService:
    feedback: FeedbackRepository
    rate_limiter: RateLimiter
    outbox: OutboxRepository

    async def submit(
        self, user: User, *, message: str, device_os: str, app_version: str
    ) -> Feedback:
        """Store the message and queue it for the support mailbox.

        Both go in the transaction of the request: there is no record without its
        email, and no email about a record that was not saved.

        The account comes from the session and never from the body: whoever sends
        this cannot report in the name of somebody else.
        """
        await self.guard_limit(user)

        feedback = Feedback(
            id=uuid.uuid4(),
            user_id=user.id,
            handle=user.handle,
            message=message,
            device_os=device_os,
            app_version=app_version,
            created_at=datetime.now(UTC),
        )
        await self.feedback.add(feedback)
        await self.outbox.add(events.feedback_submitted(feedback))
        return feedback

    async def guard_limit(self, user: User) -> None:
        sent = await self.rate_limiter.hit(
            feedback_limit_key(user.id), window_seconds=WINDOW_MINUTES * 60
        )
        if sent > MAX_MESSAGES:
            raise ProblemError(
                status=429,
                code="too-many-feedback-messages",
                title="Demasiados mensajes",
                detail=f"Ya enviaste {MAX_MESSAGES} mensajes. Esperá {WINDOW_MINUTES} minutos",
                headers={"Retry-After": str(WINDOW_MINUTES * 60)},
            )
