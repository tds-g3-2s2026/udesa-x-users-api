import re

from pydantic import BaseModel, EmailStr, Field, field_validator

# Starts with @, then 4 to 15 characters, letters, digits and underscores only.
# The @ is read as a prefix and not counted towards the length; worth confirming
# with the tutor, since the wording is ambiguous.
HANDLE_PATTERN = re.compile(r"^@[a-zA-Z0-9_]{4,15}$")

# At least 8 characters, one uppercase letter and one digit.
PASSWORD_MIN_LENGTH = 8


def enforce_password_policy(value: str) -> str:
    """The password policy, in one place.

    Registration and password reset have to apply the same rules, so they share
    this function instead of each keeping a copy that could drift apart.
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
    # The user logs in with either the email or the handle.
    identifier: str = Field(min_length=1)
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
