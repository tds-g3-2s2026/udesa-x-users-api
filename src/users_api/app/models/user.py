"""What an account is, in plain Python.

No SQLAlchemy here on purpose. This class carries the rules that answer
questions about an account, and those rules do not change if the data moves to
another engine. The table that stores it lives in
`infrastructure/database/models.py`.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Role(StrEnum):
    """Who can do what. Two administrator roles, per decision D5 in PLANIFICACION.md."""

    USER = "user"
    MODERATOR = "moderator"
    SUPERADMIN = "superadmin"


@dataclass
class User:
    email: str
    handle: str
    password_hash: str
    id: uuid.UUID | None = None
    role: Role = Role.USER
    is_email_verified: bool = False
    is_suspended: bool = False
    deleted_at: datetime | None = None
    terms_accepted: bool = False
    terms_accepted_at: datetime | None = None
    created_at: datetime | None = None

    @property
    def can_log_in(self) -> bool:
        """Suspended by an admin and self-deleted deny access the same way."""
        return not self.is_suspended and self.deleted_at is None

    @property
    def is_administrator(self) -> bool:
        """Moderators and superadmins get into the backoffice; users do not."""
        return self.role is not Role.USER
