"""Historial administrativo inmutable."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a61d24b07f32"
down_revision = "4edf59f3f5df"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("actor_email", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.CheckConstraint(
            "action IN ('admin.created', 'admin.temporary_password_reset', "
            "'user.blocked', 'report.dismissed', 'report.resolved')",
            name="ck_admin_audit_action",
        ),
    )
    op.execute("CREATE INDEX ix_admin_audit_order ON admin_audit_log (occurred_at DESC, id DESC)")
    op.execute("""
        CREATE FUNCTION refuse_admin_audit_changes() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Administrative audit entries are immutable';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER admin_audit_immutable
        BEFORE UPDATE OR DELETE OR TRUNCATE ON admin_audit_log
        FOR EACH STATEMENT EXECUTE FUNCTION refuse_admin_audit_changes()
    """)


def downgrade() -> None:
    op.drop_table("admin_audit_log")
    op.execute("DROP FUNCTION refuse_admin_audit_changes()")
