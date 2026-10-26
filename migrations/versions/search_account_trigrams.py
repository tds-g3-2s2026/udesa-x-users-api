"""Index public account discovery."""

from alembic import op

revision = "search_account_trigrams"
down_revision = "4edf59f3f5df"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for column in ("handle", "display_name"):
        op.create_index(
            f"ix_users_{column}_trgm",
            "users",
            [column],
            postgresql_using="gin",
            postgresql_ops={column: "gin_trgm_ops"},
        )


def downgrade() -> None:
    for column in ("handle", "display_name"):
        op.drop_index(f"ix_users_{column}_trgm", table_name="users")
