"""agregar perfil a usuarios

Dos columnas de texto libre, ambas nulables porque una cuenta recien creada
todavia no las completo: `display_name`, el nombre visible, y `bio`. El handle
sigue siendo el identificador unico; estas son solo lo que se muestra.

Sin limite de longitud en la base: el limite de caracteres lo aplica el
esquema de Pydantic antes de que el dato llegue aca, y duplicarlo como
`VARCHAR(n)` solo daria un segundo lugar donde el numero pudiera desalinearse.

Revision ID: 29dd98cf2961
Revises: 844b52480a02
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "29dd98cf2961"
down_revision: str | None = "844b52480a02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("bio", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "bio")
    op.drop_column("users", "display_name")
