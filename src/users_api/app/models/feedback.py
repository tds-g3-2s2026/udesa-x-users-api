"""A comment or a bug report sent from the app."""

import uuid
from dataclasses import dataclass
from datetime import datetime


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
