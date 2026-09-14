"""esquema actual

Una sola migración, en vez de una cadena creciente por historia. El sistema no
tiene todavía una base deployeada con datos reales, así que no hay nada que una
migración incremental esté protegiendo: reescribir esta migración a medida que
el modelo cambia cuesta lo mismo que sumar una nueva y evita ir arrastrando
cuatro, cinco, diez archivos que documentan una historia que nadie corrió nunca
contra datos de verdad.

El día que haya un primer deploy real, esta migración pasa a ser la base fija
y ahí sí empiezan las incrementales: en ese momento hay filas existentes que
proteger y una migración editada en el lugar dejaría de tener sentido.

Revision ID: afd5e72dc2ed
Revises:
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "afd5e72dc2ed"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_CHECK = "role IN ('user', 'moderator', 'superadmin')"
PROFILE_VISIBILITY_CHECK = "profile_visibility IN ('public', 'protected')"
FEED_LANGUAGE_CHECK = "feed_language IN ('es', 'en', 'all')"


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        # Uniqueness is case-insensitive: both values are normalised to
        # lowercase before they are stored or looked up, so the unique index
        # enforces it without needing citext or a functional index.
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("handle", sa.String(length=16), nullable=False),
        # Only the argon2id digest is stored, never the password.
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        # A temporary password is stored hashed like any other, so this flag
        # is the only thing that tells one apart.
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        # Text plus a CHECK and not a native ENUM: adding a value is then an
        # ordinary migration instead of an `ALTER TYPE` outside a transaction.
        sa.Column("role", sa.String(length=16), server_default="user", nullable=False),
        sa.Column("is_email_verified", sa.Boolean(), nullable=False),
        sa.Column("is_suspended", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terms_accepted", sa.Boolean(), nullable=False),
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
        # Unbounded on purpose: the length limit is a business rule enforced
        # by the Pydantic schema before the value reaches this table.
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column(
            "profile_visibility", sa.String(length=16), server_default="public", nullable=False
        ),
        sa.Column("feed_language", sa.String(length=16), server_default="all", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(ROLE_CHECK, name="ck_users_role"),
        sa.CheckConstraint(PROFILE_VISIBILITY_CHECK, name="ck_users_profile_visibility"),
        sa.CheckConstraint(FEED_LANGUAGE_CHECK, name="ck_users_feed_language"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_handle"), "users", ["handle"], unique=True)

    # Same shape on purpose: both solve a one-time token with an expiry, but
    # they stay apart because the verification link lasts twenty four hours
    # and the reset link ten minutes, and consuming one must not touch the
    # other. Only the digest is stored, never the raw token, so a leaked
    # database dump cannot be used to take over an account.
    for table_name in ("email_verification_tokens", "password_reset_tokens"):
        op.create_table(
            table_name,
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f(f"ix_{table_name}_token_hash"), table_name, ["token_hash"], unique=True
        )
        op.create_index(op.f(f"ix_{table_name}_user_id"), table_name, ["user_id"], unique=False)


def downgrade() -> None:
    for table_name in ("password_reset_tokens", "email_verification_tokens"):
        op.drop_index(op.f(f"ix_{table_name}_user_id"), table_name=table_name)
        op.drop_index(op.f(f"ix_{table_name}_token_hash"), table_name=table_name)
        op.drop_table(table_name)

    op.drop_index(op.f("ix_users_handle"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
