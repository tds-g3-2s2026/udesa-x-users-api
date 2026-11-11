"""A comment or a bug report sent from the app."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class FeedbackStatus(StrEnum):
    """Where a message stands in the backoffice inbox.

    It only moves forward: a message read or resolved is never sent back.
    """

    PENDING = "pending"
    READ = "read"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class Feedback:
    """What was sent, frozen as it arrived.

    The handle is a copy and not a lookup: the record has to keep saying who sent
    it after that account is deleted or blocked.
    """

    id: uuid.UUID
    user_id: uuid.UUID
    handle: str
    message: str
    device_os: str
    app_version: str
    created_at: datetime
    status: FeedbackStatus = FeedbackStatus.PENDING


@dataclass(frozen=True)
class InboxEntry:
    """A message as the backoffice lists it.

    `account_available` says whether the sender still has an account to open.
    A blocked one does; a deleted one does not.
    """

    feedback: Feedback
    account_available: bool
