"""app role and row level security

Revision ID: dd2bf16606b9
Revises: 8f2a84232d84
Create Date: 2026-09-21 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dd2bf16606b9"
down_revision: str | Sequence[str] | None = "8f2a84232d84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ("products", "suppliers")
CONDITION = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'stockpilot_app') THEN
                CREATE ROLE stockpilot_app LOGIN PASSWORD 'stockpilot_app'
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
            END IF;
        END
        $$;
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO stockpilot_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO stockpilot_app"
    )
    op.execute("REVOKE ALL ON alembic_version FROM stockpilot_app")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO stockpilot_app"
    )

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

    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM stockpilot_app"
    )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM stockpilot_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM stockpilot_app")
