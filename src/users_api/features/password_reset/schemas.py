from pydantic import BaseModel, Field, ValidationInfo, field_validator

from users_api.features.auth.schemas import PASSWORD_MIN_LENGTH, enforce_password_policy


class ForgotPasswordRequest(BaseModel):
    # The link can be asked for with either the email or the handle, same as the
    # login accepts both.
    identifier: str = Field(min_length=1)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH)
    password_confirmation: str = Field(min_length=1)

    @field_validator("password")
    @classmethod
    def password_must_meet_policy(cls, value: str) -> str:
        # The same rules registration applies, from the same function.
        return enforce_password_policy(value)

    @field_validator("password_confirmation")
    @classmethod
    def confirmation_must_match(cls, value: str, info: ValidationInfo) -> str:
        """Require the double confirmation.

        Validated on the confirmation field and not on the whole model so that
        the error carries the field that has to be highlighted; a model level
        check reports an empty field name and the app cannot tell which input to
        mark. Checked here and not only in the app, so the guarantee does not
        depend on the client.

        When the password itself broke the policy it is missing from info.data,
        and reporting a mismatch on top of that would only add noise.
        """
        if "password" in info.data and value != info.data["password"]:
            raise ValueError("Las contraseñas no coinciden")
        return value
