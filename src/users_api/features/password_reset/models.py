import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from users_api.core.db import Base
from users_api.features.auth.models import User


class PasswordResetToken(Base):
    """Same shape as the verification token, different lifecycle.

    The two tables are kept apart on purpose: a reset link lives ten minutes and
    a verification link twenty four hours, and consuming one must not touch the
    other. Sharing a declarative mixin for six columns would buy less than it
    costs to read.
    """

    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    # Only the digest is stored, as with the verification token: a database dump
    # must not be enough to take over an account.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    # Ten minutes. used_at is what makes the link single use, and it is also
    # stamped on the sibling tokens when one of them is consumed.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="password_reset_tokens")

    def is_usable(self, now: datetime) -> bool:
        return self.used_at is None and self.expires_at > now
