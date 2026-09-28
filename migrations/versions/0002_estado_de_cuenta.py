"""estado de cuenta

Reemplaza `is_suspended` por `status`, que suma el estado "En revisión" de la
E3-H5. Una columna y no un booleano por motivo: los estados se excluyen entre
sí, y con dos booleanos podría existir una cuenta suspendida y en revisión a la
vez sin que nadie sepa qué mensaje mostrarle.

Es la primera migración incremental: el servicio ya está desplegado, así que
`0001` quedó como base fija y las cuentas existentes se migran con su estado.

Revision ID: 5c2f8a91d3e4
Revises: afd5e72dc2ed
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5c2f8a91d3e4"
down_revision: str | None = "afd5e72dc2ed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUS_CHECK = "status IN ('active', 'suspended', 'under_review')"


def upgrade() -> None:
    # Text plus a CHECK and not a native ENUM, like `role`: adding a state later
    # is then an ordinary migration instead of an `ALTER TYPE`.
    op.add_column(
        "users",
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
    )
    op.execute("UPDATE users SET status = 'suspended' WHERE is_suspended")
    op.create_check_constraint("ck_users_status", "users", STATUS_CHECK)
    op.drop_column("users", "is_suspended")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_suspended", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    # An account under review goes back to suspended: the old schema has no
    # state of its own for it, and letting it log in again would undo the
    # revocation that put it there.
    op.execute("UPDATE users SET is_suspended = status <> 'active'")
    op.alter_column("users", "is_suspended", server_default=None)
    op.drop_constraint("ck_users_status", "users", type_="check")
    op.drop_column("users", "status")
