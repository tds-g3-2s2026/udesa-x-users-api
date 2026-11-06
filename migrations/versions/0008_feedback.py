"""Comentarios y reportes de error enviados desde la app.

`user_id` no tiene clave foránea a propósito, como `outbox` y `admin_audit_log`: el
registro tiene que sobrevivir a la cuenta, y por eso también copia el handle.
"""

import sqlalchemy as sa
from alembic import op

revision = "b83f0c1d7e52"
down_revision = "d14a6e2f9c07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("handle", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("device_os", sa.Text(), nullable=False),
        sa.Column("app_version", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("feedback")
