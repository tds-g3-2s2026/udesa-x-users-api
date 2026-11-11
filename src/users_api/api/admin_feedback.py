"""The comments and bug reports users send from the app, as the backoffice reads them.

Open to any administrator, like the account search: answering what users report is
support work, not management of administrators.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from users_api.api.deps import AdministratorDep, FeedbackRepositoryDep
from users_api.api.schemas.admin_feedback import FeedbackInboxItem, FeedbackInboxPage
from users_api.app.models.feedback import FeedbackStatus, InboxEntry
from users_api.app.services.admin_feedback import AdminFeedbackService

router = APIRouter(prefix="/admin/feedback", tags=["admin"])


async def get_admin_feedback_service(feedback: FeedbackRepositoryDep) -> AdminFeedbackService:
    return AdminFeedbackService(feedback=feedback)


ServiceDep = Annotated[AdminFeedbackService, Depends(get_admin_feedback_service)]


def to_response(entry: InboxEntry) -> FeedbackInboxItem:
    feedback = entry.feedback
    return FeedbackInboxItem(
        id=str(feedback.id),
        user_id=str(feedback.user_id),
        handle=feedback.handle,
        account_available=entry.account_available,
        message=feedback.message,
        device_os=feedback.device_os,
        app_version=feedback.app_version,
        status=feedback.status,
        created_at=feedback.created_at,
    )


@router.get("")
async def list_feedback(
    _: AdministratorDep,
    service: ServiceDep,
    status: Annotated[FeedbackStatus, Query()] = FeedbackStatus.PENDING,
    cursor: Annotated[str | None, Query()] = None,
) -> FeedbackInboxPage:
    """The messages in `status`, the pending ones unless asked, newest first."""
    entries, next_cursor = await service.inbox(status, cursor=cursor)
    return FeedbackInboxPage(items=[to_response(one) for one in entries], next_cursor=next_cursor)


@router.post("/{feedback_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_feedback_read(
    feedback_id: uuid.UUID, _: AdministratorDep, service: ServiceDep
) -> Response:
    await service.mark_read(feedback_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{feedback_id}/resolve", status_code=status.HTTP_204_NO_CONTENT)
async def resolve_feedback(
    feedback_id: uuid.UUID, _: AdministratorDep, service: ServiceDep
) -> Response:
    await service.resolve(feedback_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
