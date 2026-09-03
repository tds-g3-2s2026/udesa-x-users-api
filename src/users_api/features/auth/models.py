import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from users_api.core.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Uniqueness is case-insensitive. The value is normalised to lowercase
    # before it is stored or looked up, so the unique index enforces it without
    # needing citext or a functional index.
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    handle: Mapped[str] = mapped_column(String(16), unique=True, index=True)

    # Only the argon2id digest is stored, never the password.
    password_hash: Mapped[str] = mapped_column(String(255))

    # No access until the emailed token is consumed.
    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    # Suspended by an admin, or soft-deleted by the user. Both deny login with
    # the same message.
    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # The registration flow fills these in; the consent checkbox itself lives in
    # the mobile app.
    terms_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    verification_tokens: Mapped[list["EmailVerificationToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    password_reset_tokens: Mapped[list["PasswordResetToken"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def can_log_in(self) -> bool:
        return not self.is_suspended and self.deleted_at is None


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    # Only the digest is stored. A leaked database dump cannot be used to verify
    # somebody else's account.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    # The link expires and the user can request a new one.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="verification_tokens")

    def is_usable(self, now: datetime) -> bool:
        return self.used_at is None and self.expires_at > now
