"""The SQLAlchemy tables.

All of them together in one module because they reference each other and
Alembic compares the whole metadata at once: a model declared somewhere that is
never imported gets read as a table to drop.

These classes are storage, not business rules. The rules about what an account
can do live on the dataclasses under each feature's `domain.py`.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from users_api.infrastructure.database.session import Base


class UserModel(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'moderator', 'superadmin')", name="ck_users_role"),
    )

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

    # Text plus a CHECK rather than a native ENUM: adding a value is then an
    # ordinary migration instead of an ALTER TYPE outside a transaction. The
    # allowed values are the `Role` enum in `app/models/user.py`.
    role: Mapped[str] = mapped_column(String(16), default="user", server_default="user")

    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    terms_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    verification_tokens: Mapped[list["EmailVerificationTokenModel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    password_reset_tokens: Mapped[list["PasswordResetTokenModel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class EmailVerificationTokenModel(Base):
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

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[UserModel] = relationship(back_populates="verification_tokens")


class PasswordResetTokenModel(Base):
    """Kept apart from the verification token even though the columns match.

    A reset link lives ten minutes and a verification link twenty four hours,
    and consuming one must not touch the other. Sharing a declarative mixin for
    six columns would buy less than it costs to read.
    """

    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[UserModel] = relationship(back_populates="password_reset_tokens")
