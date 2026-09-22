"""row level security for stock, batches, suppliers links and import jobs

Revision ID: 1d6f193a3e83
Revises: 26d9d2c52ce2
Create Date: 2026-09-22 11:26:13.932930

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1d6f193a3e83"
down_revision: str | Sequence[str] | None = "26d9d2c52ce2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ("product_suppliers", "stock_movements", "batches", "import_jobs")
CONDITION = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"


def upgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({CONDITION}) WITH CHECK ({CONDITION})"
        )


def downgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
