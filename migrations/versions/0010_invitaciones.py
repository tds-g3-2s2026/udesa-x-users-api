"""Quién invitó a cada cuenta.

`invited_by_id` apunta a `users.id` sin `ON DELETE`: una baja es lógica (`deleted_at`) y la
fila queda, así que la referencia nunca queda colgada.
"""

import sqlalchemy as sa
from alembic import op

revision = "e52c8a41b9d3"
down_revision = "9c7ce29bf265"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("invited_by_id", sa.UUID(), nullable=True))
    op.create_foreign_key("fk_users_invited_by_id", "users", "users", ["invited_by_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_users_invited_by_id", "users", type_="foreignkey")
    op.drop_column("users", "invited_by_id")
