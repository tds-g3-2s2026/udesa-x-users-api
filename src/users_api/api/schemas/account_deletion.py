"""What the owner sends to close their own account."""

from pydantic import BaseModel, Field


class DeleteAccountRequest(BaseModel):
    """Only the current password, which proves the session belongs to the owner.

    No shape is demanded of it beyond not being empty: it is checked against the
    stored hash, and a rule here would leak what the password policy used to be.
    """

    current_password: str = Field(min_length=1)
