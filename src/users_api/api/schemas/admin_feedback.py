from datetime import datetime

from pydantic import BaseModel

from users_api.app.models.feedback import FeedbackStatus


class FeedbackInboxItem(BaseModel):
    id: str
    user_id: str
    # The handle the account had when it sent the message, never the current one.
    handle: str
    account_available: bool
    message: str
    device_os: str
    app_version: str
    status: FeedbackStatus
    created_at: datetime


class FeedbackInboxPage(BaseModel):
    items: list[FeedbackInboxItem]
    # Echoed back as `?cursor=` for the next page; null once there is none.
    next_cursor: str | None
