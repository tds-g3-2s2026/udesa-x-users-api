"""The profile a user edits about themselves.

The email and the handle live outside this schema on purpose: the email never
changes here, and the handle was already fixed at registration. `display_name`
and `bio` are the only two fields a user can touch.
"""

import nh3
from pydantic import BaseModel, ConfigDict, Field, field_validator

# The consigna sets 160 for the bio. Nothing sets one for the display name, so
# this picks X's limit for the same kind of field: short enough to fit a
# header, long enough for a real name.
DISPLAY_NAME_MAX_LENGTH = 50
BIO_MAX_LENGTH = 160


def sanitize_text(value: str) -> str:
    """Strip HTML and scripts.

    `nh3` wraps the same Rust sanitizer (`ammonia`) used across the Rust and
    Python ecosystems, kept current unlike `bleach`. An empty tag allowlist
    means no markup survives: a `<script>` loses its content outright, any
    other tag is unwrapped and its text kept, so a display name or a bio can
    never carry anything but plain text.
    """
    return nh3.clean(value, tags=set()).strip()


class ProfileResponse(BaseModel):
    id: str
    email: str
    handle: str
    display_name: str | None
    bio: str | None


class UpdateProfileRequest(BaseModel):
    """A partial update: only the fields present in the payload change.

    `extra="forbid"` is what rejects `email` and `handle` with a 422 instead
    of silently ignoring them — a client that thinks it changed the email and
    did not is worse off than one that gets told it cannot.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=DISPLAY_NAME_MAX_LENGTH)
    bio: str | None = Field(default=None, max_length=BIO_MAX_LENGTH)

    @field_validator("display_name")
    @classmethod
    def display_name_is_required_when_present(cls, value: str | None) -> str:
        """Blank, whitespace-only or explicit null are all refused.

        Pydantic only calls this when the key is present in the payload at
        all — omitting `display_name` entirely skips validation and leaves it
        unchanged, which is what makes this a partial update and not a form
        that has to be resent whole.
        """
        cleaned = sanitize_text(value) if value is not None else ""
        if not cleaned:
            raise ValueError("El nombre visible no puede quedar vacío")
        return cleaned

    @field_validator("bio")
    @classmethod
    def bio_is_sanitized(cls, value: str | None) -> str | None:
        return sanitize_text(value) if value is not None else None
