"""outbox

Tabla del outbox transaccional (issue #30): cada evento que publica el
servicio se escribe acá, en la misma transacción que el cambio de estado que lo
causó, y el publicador lo manda a RabbitMQ y borra la fila cuando el broker lo
confirma.

El trigger avisa con `pg_notify` en cada INSERT. La notificación se entrega
recién cuando la transacción commitea, así que el publicador nunca se despierta
por una fila que todavía no puede ver.

Revision ID: c7a3e91f5b28
Revises: 9e41b7c2a6d0
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7a3e91f5b28"
down_revision: str | None = "9e41b7c2a6d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbox",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_outbox_created_at"), "outbox", ["created_at"], unique=False)
    op.execute(
        """
        CREATE FUNCTION outbox_notify() RETURNS trigger AS $$
        BEGIN
            PERFORM pg_notify('outbox', NEW.id::text);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER outbox_notify_after_insert
        AFTER INSERT ON outbox
        FOR EACH ROW EXECUTE FUNCTION outbox_notify()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER outbox_notify_after_insert ON outbox")
    op.execute("DROP FUNCTION outbox_notify()")
    op.drop_index(op.f("ix_outbox_created_at"), table_name="outbox")
    op.drop_table("outbox")
