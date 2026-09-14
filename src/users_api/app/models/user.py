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


class ProfileVisibility(StrEnum):
    """Who can see a user's posts: everyone, or only approved followers."""

    PUBLIC = "public"
    PROTECTED = "protected"


class FeedLanguage(StrEnum):
    """What language the feed's content is shown in.

    Filtering the feed by this is a later story; for now the value is only
    stored and returned.
    """

    ES = "es"
    EN = "en"
    ALL = "all"


@dataclass
class User:
    email: str
    handle: str
    password_hash: str
    id: uuid.UUID | None = None
    role: Role = Role.USER
    # Raised when the password was not chosen by the owner: an administrator
    # created the account with a temporary one. It stays raised until the
    # owner replaces it.
    must_change_password: bool = False
    is_email_verified: bool = False
    is_suspended: bool = False
    deleted_at: datetime | None = None
    terms_accepted: bool = False
    terms_accepted_at: datetime | None = None
    created_at: datetime | None = None
    # The name shown to other people and a short biography, both unset until
    # the owner fills them in. The handle stays the identifier; these are
    # only what gets displayed.
    display_name: str | None = None
    bio: str | None = None
    # Assigned at registration and editable afterwards. Public and every
    # language are the defaults: they open the account up rather than
    # narrowing it, so a user who never visits the settings screen is not
    # silently hidden or missing content.
    profile_visibility: ProfileVisibility = ProfileVisibility.PUBLIC
    feed_language: FeedLanguage = FeedLanguage.ALL

    @property
    def can_log_in(self) -> bool:
        """Suspended by an admin and self-deleted deny access the same way."""
        return not self.is_suspended and self.deleted_at is None

    @property
    def is_administrator(self) -> bool:
        """Moderators and superadmins get into the backoffice; users do not."""
        return self.role is not Role.USER
