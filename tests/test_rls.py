import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import settings
from tests.helpers import db_scalar

TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"
SET_TENANT = text("SELECT set_config('app.current_tenant', :tenant, true)")


@pytest.fixture
async def seeded(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as conn:
        await conn.execute(
            text(f"INSERT INTO tenants (id, name) VALUES ('{TENANT_A}', 'A'), ('{TENANT_B}', 'B')")
        )
        await conn.execute(
            text(
                "INSERT INTO products (id, tenant_id, sku, name, is_active) VALUES "
                f"(gen_random_uuid(), '{TENANT_A}', 'A-1', 'A product', true), "
                f"(gen_random_uuid(), '{TENANT_B}', 'B-1', 'B product', true)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO suppliers (id, tenant_id, name) VALUES "
                f"(gen_random_uuid(), '{TENANT_A}', 'A supplier'), "
                f"(gen_random_uuid(), '{TENANT_B}', 'B supplier')"
            )
        )


async def test_app_role_cannot_bypass_row_level_security(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        )
        assert tuple(result.one()) == (False, False)


@pytest.mark.parametrize("table", ["products", "suppliers"])
async def test_no_tenant_set_means_no_rows(
    app_engine: AsyncEngine, seeded: None, table: str
) -> None:
    async with app_engine.connect() as conn:
        count = (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
    assert count == 0


@pytest.mark.parametrize(
    ("table", "column", "expected"),
    [("products", "sku", "A-1"), ("suppliers", "name", "A supplier")],
)
async def test_query_without_where_only_returns_own_rows(
    app_engine: AsyncEngine, seeded: None, table: str, column: str, expected: str
) -> None:
    async with app_engine.begin() as conn:
        await conn.execute(SET_TENANT, {"tenant": TENANT_A})
        values = (await conn.execute(text(f"SELECT {column} FROM {table}"))).scalars().all()
    assert list(values) == [expected]


async def test_cannot_insert_a_row_for_another_tenant(
    app_engine: AsyncEngine, seeded: None
) -> None:
    with pytest.raises(DBAPIError, match="row-level security"):
        async with app_engine.begin() as conn:
            await conn.execute(SET_TENANT, {"tenant": TENANT_A})
            await conn.execute(
                text(
                    "INSERT INTO products (id, tenant_id, sku, name, is_active) VALUES "
                    f"(gen_random_uuid(), '{TENANT_B}', 'X-1', 'Sneaky', true)"
                )
            )


async def test_update_without_where_only_touches_own_rows(
    app_engine: AsyncEngine, seeded: None, db_engine: AsyncEngine
) -> None:
    async with app_engine.begin() as conn:
        await conn.execute(SET_TENANT, {"tenant": TENANT_A})
        result = await conn.execute(text("UPDATE products SET name = 'changed'"))
        assert result.rowcount == 1

    untouched = await db_scalar(db_engine, "SELECT name FROM products WHERE sku = 'B-1'")
    assert untouched == "B product"


async def test_tenant_setting_does_not_leak_into_the_next_transaction(seeded: None) -> None:
    engine = create_async_engine(settings.database_url, pool_size=1, max_overflow=0)
    try:
        async with engine.begin() as conn:
            await conn.execute(SET_TENANT, {"tenant": TENANT_A})
            count = (await conn.execute(text("SELECT count(*) FROM products"))).scalar_one()
            assert count == 1

        async with engine.begin() as conn:
            count = (await conn.execute(text("SELECT count(*) FROM products"))).scalar_one()
            assert count == 0
    finally:
        await engine.dispose()
