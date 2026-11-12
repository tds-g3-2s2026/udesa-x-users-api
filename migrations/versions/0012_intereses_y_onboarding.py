"""Intereses de la cuenta y marca de onboarding terminado.

`interests` arranca vacío en todas las cuentas: nadie los eligió todavía. El CHECK limita
la lista a los códigos de `Interest`.

`onboarding_completed` queda en `true` para las cuentas que ya existen y en `false` para
las nuevas. Una cuenta que ya usa la app no tiene que pasar por el onboarding, que está
pensado para antes del primer feed. Por eso la columna se agrega con `true` como valor por
defecto, lo que llena las filas existentes, y recién después el valor por defecto pasa a
`false`. Una cuenta que se registra mientras se despliega, en un pod con el código viejo,
toma `false`: es nueva y le corresponde el onboarding.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f3a9c6d21b7e"
down_revision = "e27b5d83a1c4"
branch_labels = None
depends_on = None

INTERESTS = "'sports', 'technology', 'politics', 'music', 'science', 'movies', 'gaming', 'economy'"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("interests", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
    )
    op.create_check_constraint(
        "ck_users_interests", "users", f"interests <@ ARRAY[{INTERESTS}]::text[]"
    )
    op.add_column(
        "users",
        sa.Column("onboarding_completed", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column("users", "onboarding_completed", server_default=sa.false())


def downgrade() -> None:
    op.drop_column("users", "onboarding_completed")
    op.drop_constraint("ck_users_interests", "users", type_="check")
    op.drop_column("users", "interests")
