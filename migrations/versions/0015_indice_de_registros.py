"""Índice sobre la fecha de creación de las cuentas.

Lo usa el conteo de registros por día del dashboard del backoffice, que filtra las cuentas por
un rango de `created_at`. Sin el índice, esa consulta recorre la tabla entera.
"""

from alembic import op

revision = "3762ea011f2e"
down_revision = "ed0bd788fcf0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_users_created_at", "users", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_users_created_at", table_name="users")
