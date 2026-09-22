import uuid
from datetime import UTC, datetime

import numpy as np
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models import MovementType, Product, StockMovement
from app.services.forecast_data import load_tenant_history
from tests.helpers import register


async def _add_product(
    db_engine: AsyncEngine, tenant_id, sku: str, price: float | None
) -> uuid.UUID:
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        product = Product(tenant_id=tenant_id, sku=sku, name=sku, current_price=price)
        session.add(product)
        await session.commit()
        return product.id


async def _add_sale(
    db_engine: AsyncEngine, tenant_id, product_id, day_offset: int, qty: int
) -> None:
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        session.add(
            StockMovement(
                tenant_id=tenant_id,
                product_id=product_id,
                movement_type=MovementType.SALE,
                quantity=-qty,
                occurred_at=datetime(2024, 1, 1 + day_offset, tzinfo=UTC),
            )
        )
        await session.commit()


async def test_empty_history_returns_empty_grid(client, db_engine: AsyncEngine) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        history = await load_tenant_history(session, tenant_id)
    assert history.values.shape == (0, 0)
    assert history.product_ids == []


async def test_interior_gaps_become_zero_outside_stays_nan(client, db_engine: AsyncEngine) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    product_id = await _add_product(db_engine, tenant_id, "A1", price=9.99)

    # Sales on day 0 and day 4 only; days 1-3 are interior gaps, days 5+ never happened.
    await _add_sale(db_engine, tenant_id, product_id, day_offset=0, qty=3)
    await _add_sale(db_engine, tenant_id, product_id, day_offset=4, qty=2)

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        history = await load_tenant_history(session, tenant_id)

    assert history.n_days == 5
    row = history.values[0]
    assert row[0] == 3.0
    assert row[1] == 0.0
    assert row[2] == 0.0
    assert row[3] == 0.0
    assert row[4] == 2.0


async def test_price_is_constant_across_a_products_active_range(
    client, db_engine: AsyncEngine
) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    product_id = await _add_product(db_engine, tenant_id, "A1", price=5.50)
    await _add_sale(db_engine, tenant_id, product_id, day_offset=0, qty=1)
    await _add_sale(db_engine, tenant_id, product_id, day_offset=3, qty=1)

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        history = await load_tenant_history(session, tenant_id)

    assert np.all(history.prices[0, 0:4] == 5.5)


async def test_multiple_products_get_separate_rows_in_sorted_order(
    client, db_engine: AsyncEngine
) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    product_b = await _add_product(db_engine, tenant_id, "B1", price=1.0)
    product_a = await _add_product(db_engine, tenant_id, "A1", price=2.0)
    await _add_sale(db_engine, tenant_id, product_a, day_offset=0, qty=5)
    await _add_sale(db_engine, tenant_id, product_b, day_offset=0, qty=7)

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        history = await load_tenant_history(session, tenant_id)

    assert len(history.product_ids) == 2
    row_a = history.product_ids.index(product_a)
    row_b = history.product_ids.index(product_b)
    assert history.values[row_a, 0] == 5.0
    assert history.values[row_b, 0] == 7.0


async def test_two_sales_same_day_are_summed(client, db_engine: AsyncEngine) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    product_id = await _add_product(db_engine, tenant_id, "A1", price=3.0)
    await _add_sale(db_engine, tenant_id, product_id, day_offset=0, qty=2)
    await _add_sale(db_engine, tenant_id, product_id, day_offset=0, qty=3)

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        history = await load_tenant_history(session, tenant_id)

    assert history.values[0, 0] == 5.0


async def test_only_this_tenants_data_is_loaded(client, db_engine: AsyncEngine) -> None:
    user_a = await register(client, "Shop A", "a@example.com")
    user_b = await register(client, "Shop B", "b@example.com")
    tenant_a, tenant_b = uuid.UUID(user_a["tenant_id"]), uuid.UUID(user_b["tenant_id"])
    product_a = await _add_product(db_engine, tenant_a, "A1", price=1.0)
    await _add_sale(db_engine, tenant_a, product_a, day_offset=0, qty=1)

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        history_a = await load_tenant_history(session, tenant_a)
        history_b = await load_tenant_history(session, tenant_b)

    assert len(history_a.product_ids) == 1
    assert history_b.values.shape == (0, 0)
