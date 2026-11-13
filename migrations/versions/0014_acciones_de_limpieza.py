"""Las dos acciones de limpieza de contenido en la auditoría (E5-H10).

`user.content_cleaned` la registra users-api al limpiar una biografía, y
`post.content_cleaned` llega de posts-api con `admin.action_recorded.v1` al limpiar un post.

El downgrade falla si ya hay limpiezas registradas: la auditoría no se borra.
"""

from alembic import op

revision = "ed0bd788fcf0"
down_revision = "a6d40e9b3c18"
branch_labels = None
depends_on = None

BEFORE = (
    "action IN ('admin.created', 'admin.temporary_password_reset', "
    "'user.blocked', 'report.dismissed', 'report.resolved')"
)
AFTER = (
    "action IN ('admin.created', 'admin.temporary_password_reset', "
    "'user.blocked', 'report.dismissed', 'report.resolved', "
    "'user.content_cleaned', 'post.content_cleaned')"
)


def upgrade() -> None:
    op.drop_constraint("ck_admin_audit_action", "admin_audit_log", type_="check")
    op.create_check_constraint("ck_admin_audit_action", "admin_audit_log", AFTER)


def downgrade() -> None:
    op.drop_constraint("ck_admin_audit_action", "admin_audit_log", type_="check")
    op.create_check_constraint("ck_admin_audit_action", "admin_audit_log", BEFORE)
