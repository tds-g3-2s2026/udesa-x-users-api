"""motivo del estado

Suma a `users` el motivo y el instante del último cambio de estado. El bloqueo de
un administrador (E5-H5) exige un motivo y el detalle del backoffice lo muestra
junto al estado; la revisión por denuncias (E3-H5) deja solo el instante.

Las dos columnas aceptan NULL y no se completan para las cuentas existentes:
ninguna cambió de estado con un motivo guardado, y no hay un valor verdadero
para inventarles.

Revision ID: 4edf59f3f5df
Revises: c7a3e91f5b28
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4edf59f3f5df"
down_revision: str | None = "c7a3e91f5b28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Unbounded text, like `display_name`: the length limit is the request's rule.
    op.add_column("users", sa.Column("status_reason", sa.Text(), nullable=True))
    op.add_column(
        "users", sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "status_changed_at")
    op.drop_column("users", "status_reason")
