"""What the app sends with a comment or a bug report."""

from pydantic import BaseModel, Field, field_validator

MESSAGE_MAX_LENGTH = 500
DEVICE_OS_MAX_LENGTH = 64
APP_VERSION_MAX_LENGTH = 32
# The device data goes into the support email line by line, so a line break here
# would let a client add lines of its own.
SINGLE_LINE = r"^[^\x00-\x1f\x7f]+$"


class SubmitFeedbackRequest(BaseModel):
    """The text the user typed and the device data the app adds on its own.

    The text is not sanitized: nobody renders it as HTML (the email is plain text
    and the backoffice escapes it), and a bug report about a `<script>` tag has to
    arrive saying that. The account is not here either, it comes from the session.
    """

    message: str = Field(max_length=MESSAGE_MAX_LENGTH)
    device_os: str = Field(min_length=1, max_length=DEVICE_OS_MAX_LENGTH, pattern=SINGLE_LINE)
    app_version: str = Field(min_length=1, max_length=APP_VERSION_MAX_LENGTH, pattern=SINGLE_LINE)

    @field_validator("message")
    @classmethod
    def message_must_have_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("El mensaje no puede quedar vacío")
        return stripped
