from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from users_api.api.schemas.auth import enforce_handle_format

# Enough to explain a sanction in a few sentences.
BLOCK_REASON_MAX_LENGTH = 500


class CreateAdministratorRequest(BaseModel):
    email: EmailStr
    # Asked for and not derived from the email: the handle has its own shape
    # and has to be unique, and a rule that guesses one satisfying both is
    # something nobody could predict from the panel.
    handle: str = Field(min_length=5, max_length=16)
    # `user` is missing on purpose: this endpoint creates administrators.
    role: Literal["moderator", "superadmin"]

    @field_validator("handle")
    @classmethod
    def handle_must_match_format(cls, value: str) -> str:
        return enforce_handle_format(value)


class AdministratorCredentialResponse(BaseModel):
    """An administrator account together with the password it was handed."""

    id: str
    email: EmailStr
    handle: str
    role: str
    # The only time this travels in clear. Whoever created the account has to
    # pass it on now, because the service keeps no copy it could show again.
    temporary_password: str


class AdministratorResponse(BaseModel):
    id: str
    email: EmailStr
    handle: str
    role: str
    # None once the owner chose their own password. While it is set, the panel
    # knows whether the credential is still usable or has to be regenerated,
    # without having to reimplement the deadline itself.
    temporary_password_status: Literal["pending", "expired"] | None
    temporary_password_expires_at: datetime | None


class UserAccountResponse(BaseModel):
    """An app account as the backoffice sees it (E5-H4). Never a hash or a token.

    `status` travels as stored: the panel shows `suspended` as "Bloqueado".
    The followers and posts counters are posts-api's and come from there.
    """

    id: str
    email: str
    handle: str
    display_name: str | None
    status: Literal["active", "suspended", "under_review"]
    # Why and when `status` last changed. The reason only an administrator's
    # block leaves; both null on an account that never changed.
    status_reason: str | None
    status_changed_at: datetime | None
    is_email_verified: bool
    created_at: datetime


class UserAccountPage(BaseModel):
    items: list[UserAccountResponse]
    # Echoed back as `?cursor=` for the next page; null once there is none.
    next_cursor: str | None


class BlockAccountRequest(BaseModel):
    # Stripped before the limits apply, so a reason of only spaces is refused as
    # missing (CA.1) and the padding does not count against the 500.
    reason: str = Field(min_length=1, max_length=BLOCK_REASON_MAX_LENGTH)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value
