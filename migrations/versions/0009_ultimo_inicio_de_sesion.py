"""Último inicio de sesión de cada cuenta.

Lo mueve cada login exitoso, de la app o del backoffice; renovar la sesión no
cuenta. Acepta NULL y no se completa para las cuentas existentes: no hay forma de
saber cuándo entraron por última vez, y una fecha inventada mostraría como activa
una cuenta abandonada.
"""

import sqlalchemy as sa
from alembic import op

revision = "9c7ce29bf265"
down_revision = "b83f0c1d7e52"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_login_at")
