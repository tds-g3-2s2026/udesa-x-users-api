"""Estado de cada mensaje de feedback en la bandeja del backoffice.

`status` arranca en `pending` para todos los mensajes, los que ya existen incluidos: nadie
los leyó todavía desde el backoffice. Solo avanza, de `pending` a `read` y de cualquiera de
los dos a `resolved`; eso lo controla la aplicación.

El índice sirve al listado, que filtra por estado y ordena del más nuevo al más viejo.
PostgreSQL lo recorre de atrás para adelante, así que no hace falta declararlo descendente.
"""

import sqlalchemy as sa
from alembic import op

revision = "a6d40e9b3c18"
down_revision = "f3a9c6d21b7e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "feedback", sa.Column("status", sa.Text(), nullable=False, server_default="pending")
    )
    op.create_check_constraint(
        "ck_feedback_status", "feedback", "status IN ('pending', 'read', 'resolved')"
    )
    op.create_index("ix_feedback_status_created_at_id", "feedback", ["status", "created_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_feedback_status_created_at_id", table_name="feedback")
    op.drop_constraint("ck_feedback_status", "feedback", type_="check")
    op.drop_column("feedback", "status")
