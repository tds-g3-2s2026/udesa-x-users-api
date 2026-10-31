"""The SQLAlchemy tables.

All of them together in one module because they reference each other and
Alembic compares the whole metadata at once: a model declared somewhere that is
never imported gets read as a table to drop.

These classes are storage, not business rules. The rules about what an account
can do live on the dataclasses under each feature's `domain.py`.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from users_api.infrastructure.database.session import Base


class UserModel(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index(
            "ix_users_handle_trgm",
            "handle",
            postgresql_using="gin",
            postgresql_ops={"handle": "gin_trgm_ops"},
        ),
        Index(
            "ix_users_display_name_trgm",
            "display_name",
            postgresql_using="gin",
            postgresql_ops={"display_name": "gin_trgm_ops"},
        ),
        CheckConstraint("role IN ('user', 'moderator', 'superadmin')", name="ck_users_role"),
        CheckConstraint(
            "profile_visibility IN ('public', 'protected')", name="ck_users_profile_visibility"
        ),
        CheckConstraint("feed_language IN ('es', 'en', 'all')", name="ck_users_feed_language"),
        CheckConstraint(
            "status IN ('active', 'suspended', 'under_review')", name="ck_users_status"
        ),
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

    # A temporary password is stored hashed like any other, so this flag is
    # the only thing that tells one apart.
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    temporary_password_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # Text plus a CHECK rather than a native ENUM: adding a value is then an
    # ordinary migration instead of an ALTER TYPE outside a transaction. The
    # allowed values are the `Role` enum in `app/models/user.py`.
    role: Mapped[str] = mapped_column(String(16), default="user", server_default="user")

    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    # Same shape as `role`. The allowed values are the `AccountStatus` enum.
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    # Why and when `status` last changed. Unbounded like `display_name` below:
    # the length of the reason is the request's rule.
    status_reason: Mapped[str | None] = mapped_column(Text(), default=None)
    status_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    terms_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # Unbounded on purpose: the length limit is a business rule enforced by the
    # Pydantic schema before the value ever reaches this table, and repeating
    # it here as a VARCHAR(n) would only give the number a second place to
    # drift out of sync.
    display_name: Mapped[str | None] = mapped_column(Text(), default=None)
    bio: Mapped[str | None] = mapped_column(Text(), default=None)

    # Same shape as `role`: text plus a CHECK, not a native ENUM, so adding a
    # value later is an ordinary migration and not an `ALTER TYPE`.
    profile_visibility: Mapped[str] = mapped_column(
        String(16), default="public", server_default="public"
    )
    feed_language: Mapped[str] = mapped_column(String(16), default="all", server_default="all")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    verification_tokens: Mapped[list["EmailVerificationTokenModel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    password_reset_tokens: Mapped[list["PasswordResetTokenModel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list["RefreshTokenModel"]] = relationship(
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


class RefreshTokenModel(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    # Every token handed out by one login shares it. Revoking a family ends that
    # session and no other, and a token used twice is found by its family.
    family_id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), index=True)

    # Only the digest is stored, like the emailed tokens: a leaked database dump
    # cannot be turned into working sessions.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Set when the token is exchanged. A token that comes back with this set is
    # a copy somebody kept, which is what reuse detection looks for.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[UserModel] = relationship(back_populates="refresh_tokens")


class OutboxModel(Base):
    """Events waiting to be published (transactional outbox).

    The row is written in the same transaction as the change it describes and
    deleted by the publisher once the broker confirms it. No foreign key to
    users on purpose: an event must outlive whatever it talks about.
    """

    __tablename__ = "outbox"

    # The id of the event itself: it is what consumers deduplicate on.
    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    type: Mapped[str] = mapped_column(Text)

    # The whole CloudEvents envelope. It can carry secrets, so it is never logged.
    payload: Mapped[dict] = mapped_column(postgresql.JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class AuditLogModel(Base):
    __tablename__ = "admin_audit_log"
    __table_args__ = (
        CheckConstraint(
            "action IN ('admin.created', 'admin.temporary_password_reset', "
            "'user.blocked', 'report.dismissed', 'report.resolved')",
            name="ck_admin_audit_action",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), nullable=False)
    actor_email: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), nullable=False)
    details: Mapped[dict] = mapped_column(postgresql.JSONB, nullable=False, server_default="{}")


Index("ix_admin_audit_order", AuditLogModel.occurred_at.desc(), AuditLogModel.id.desc())
