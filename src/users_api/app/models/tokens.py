"""The single use tokens that travel by email.

Both share a shape and a rule —they are usable once, until they expire— and
differ in lifetime: a verification link lasts twenty four hours, a recovery link
ten minutes, because that one opens the door to the account.

They are kept as separate classes, and separate tables, so that consuming one
never touches the other.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass
class EmailVerificationToken:
    user_id: uuid.UUID
    token_hash: str
    expires_at: datetime
    id: uuid.UUID | None = None
    used_at: datetime | None = None

    def is_usable(self, now: datetime) -> bool:
        return self.used_at is None and self.expires_at > now


@dataclass
class PasswordResetToken:
    user_id: uuid.UUID
    token_hash: str
    expires_at: datetime
    id: uuid.UUID | None = None
    used_at: datetime | None = None

    def is_usable(self, now: datetime) -> bool:
        return self.used_at is None and self.expires_at > now
