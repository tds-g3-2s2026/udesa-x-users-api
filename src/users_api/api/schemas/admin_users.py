from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from users_api.api.schemas.auth import enforce_handle_format


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
