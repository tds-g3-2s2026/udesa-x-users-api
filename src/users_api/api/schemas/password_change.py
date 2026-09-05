from pydantic import BaseModel, Field, ValidationInfo, field_validator

from users_api.api.schemas.auth import (
    PASSWORD_MIN_LENGTH,
    enforce_confirmation_matches,
    enforce_password_policy,
)


class ChangePasswordRequest(BaseModel):
    """The three fields the form asks for.

    `password` and `password_confirmation` are named as in the reset so the app
    can drive both screens with the same component; what this one adds is the
    current password, which is what proves the session belongs to the owner and
    not to whoever picked up an unlocked phone.

    No minimum length on the current password: it is checked against the stored
    hash, and demanding a shape from it would leak what the policy used to be.
    """

    current_password: str = Field(min_length=1)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH)
    password_confirmation: str = Field(min_length=1)

    @field_validator("password")
    @classmethod
    def password_must_meet_policy(cls, value: str) -> str:
        # The same rules as registration and as the reset.
        return enforce_password_policy(value)

    @field_validator("password_confirmation")
    @classmethod
    def confirmation_must_match(cls, value: str, info: ValidationInfo) -> str:
        return enforce_confirmation_matches(value, info)
