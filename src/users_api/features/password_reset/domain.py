"""The recovery link, in plain Python.

Same shape as the verification token and a different lifecycle: this one lives
ten minutes because it opens the door to the account, and consuming it must not
touch the verification one.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass
class PasswordResetToken:
    user_id: uuid.UUID
    token_hash: str
    expires_at: datetime
    id: uuid.UUID | None = None
    used_at: datetime | None = None

    def is_usable(self, now: datetime) -> bool:
        return self.used_at is None and self.expires_at > now
