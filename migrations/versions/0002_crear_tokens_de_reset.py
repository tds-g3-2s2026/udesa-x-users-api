"""crear tokens de reset de contrasena

Agrega la tabla que sostiene el flujo de recuperación de E1-H5. Tiene la misma
forma que email_verification_tokens porque resuelve el mismo problema —un token
de un solo uso con vencimiento— pero se mantiene separada: el link de reset dura
diez minutos y el de validación veinticuatro horas, y consumir uno no puede
tocar al otro.

El índice único sobre token_hash es lo que hace cumplir el CA.5: solo se guarda
el digest, nunca el token, así que un dump de la base no alcanza para tomar una
cuenta ajena.

Revision ID: 3c9d2f4a17be
Revises: f61a1b957893
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3c9d2f4a17be"
down_revision: str | None = "f61a1b957893"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
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
        op.f("ix_password_reset_tokens_token_hash"),
        "password_reset_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        op.f("ix_password_reset_tokens_user_id"),
        "password_reset_tokens",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_password_reset_tokens_user_id"),
        table_name="password_reset_tokens",
    )
    op.drop_index(
        op.f("ix_password_reset_tokens_token_hash"),
        table_name="password_reset_tokens",
    )
    op.drop_table("password_reset_tokens")
