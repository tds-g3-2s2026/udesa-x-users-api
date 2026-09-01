import re

from pydantic import BaseModel, EmailStr, Field, ValidationInfo, field_validator

# E1-H1 CA.3: starts with @, then 4 to 15 characters, letters, digits and
# underscores only. The @ is read as a prefix and not counted towards the
# length; worth confirming with the tutor, since the wording is ambiguous.
HANDLE_PATTERN = re.compile(r"^@[a-zA-Z0-9_]{4,15}$")

# E1-H1 CA.4: at least 8 characters, one uppercase letter and one digit.
PASSWORD_MIN_LENGTH = 8


def enforce_password_policy(value: str) -> str:
    """The E1-H1 CA.4 policy, in one place.

    E1-H5 CA.3 asks the reset to meet "the same security policies as E1-H1", so
    registration and reset share this function instead of each keeping a copy
    that could drift apart.
    """
    if not any(character.isupper() for character in value):
        raise ValueError("La contraseña debe tener al menos una mayúscula")
    if not any(character.isdigit() for character in value):
        raise ValueError("La contraseña debe tener al menos un número")
    return value


class RegisterRequest(BaseModel):
    email: EmailStr
    handle: str = Field(min_length=5, max_length=16)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH)
    terms_accepted: bool

    @field_validator("handle")
    @classmethod
    def handle_must_match_format(cls, value: str) -> str:
        if not HANDLE_PATTERN.match(value):
            raise ValueError(
                "El handle debe empezar con @ y tener entre 4 y 15 caracteres, "
                "usando solo letras, números y guiones bajos"
            )
        return value.lower()

    @field_validator("password")
    @classmethod
    def password_must_meet_policy(cls, value: str) -> str:
        return enforce_password_policy(value)

    @field_validator("terms_accepted")
    @classmethod
    def terms_must_be_accepted(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Hay que aceptar los términos y la política de privacidad")
        return value


class RegisterResponse(BaseModel):
    id: str
    email: EmailStr
    handle: str


class VerifyRequest(BaseModel):
    token: str = Field(min_length=1)


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class LoginRequest(BaseModel):
    # E1-H2: the user logs in with either the email or the handle.
    identifier: str = Field(min_length=1)
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ForgotPasswordRequest(BaseModel):
    # E1-H5: the link can be asked for with either the email or the handle,
    # same as the login accepts both.
    identifier: str = Field(min_length=1)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH)
    password_confirmation: str = Field(min_length=1)

    @field_validator("password")
    @classmethod
    def password_must_meet_policy(cls, value: str) -> str:
        # E1-H5 CA.3: the same policy as registration, from the same function.
        return enforce_password_policy(value)

    @field_validator("password_confirmation")
    @classmethod
    def confirmation_must_match(cls, value: str, info: ValidationInfo) -> str:
        """E1-H5 CA.3, the other half: double confirmation.

        Validated on the confirmation field and not on the whole model so that
        the error carries the field that has to be highlighted; a model level
        check reports an empty field name and the app cannot tell which input
        to mark. Checked here and not only in the app, so the guarantee does
        not depend on the client.

        When the password itself broke the policy it is missing from info.data,
        and reporting a mismatch on top of that would only add noise.
        """
        if "password" in info.data and value != info.data["password"]:
            raise ValueError("Las contraseñas no coinciden")
        return value
