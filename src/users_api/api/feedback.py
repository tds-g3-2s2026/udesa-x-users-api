"""Comments and bug reports sent from the app's settings screen."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from users_api.api.deps import (
    CurrentUserDep,
    FeedbackRepositoryDep,
    OutboxRepositoryDep,
    RateLimiterDep,
)
from users_api.api.schemas.feedback import SubmitFeedbackRequest
from users_api.app.services.feedback import FeedbackService

router = APIRouter(prefix="/me", tags=["feedback"])


async def get_feedback_service(
    feedback: FeedbackRepositoryDep,
    rate_limiter: RateLimiterDep,
    outbox: OutboxRepositoryDep,
) -> FeedbackService:
    return FeedbackService(feedback=feedback, rate_limiter=rate_limiter, outbox=outbox)


ServiceDep = Annotated[FeedbackService, Depends(get_feedback_service)]


@router.post("/feedback", status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    payload: SubmitFeedbackRequest, user: CurrentUserDep, service: ServiceDep
) -> dict[str, str]:
    """Store the message and queue the email for the support account."""
    feedback = await service.submit(
        user,
        message=payload.message,
        device_os=payload.device_os,
        app_version=payload.app_version,
    )
    return {"id": str(feedback.id)}
