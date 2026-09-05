"""agregar rol a usuarios

Cada cuenta pasa a tener un rol: `user`, `moderator` o `superadmin`. Las que ya
existen quedan como `user`, que es lo que eran de hecho: hasta acá el token
llevaba ese valor fijo para todo el mundo.

Es una columna de texto con un CHECK y no un ENUM nativo de PostgreSQL. Sumar
un valor a un ENUM es un `ALTER TYPE` que no corre dentro de una transacción;
cambiar el CHECK es una migración común.

Revision ID: 844b52480a02
Revises: 3c9d2f4a17be
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "844b52480a02"
down_revision: str | None = "3c9d2f4a17be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_CHECK = "role IN ('user', 'moderator', 'superadmin')"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=16), server_default="user", nullable=False),
    )
    op.create_check_constraint("ck_users_role", "users", ROLE_CHECK)


def downgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.drop_column("users", "role")
