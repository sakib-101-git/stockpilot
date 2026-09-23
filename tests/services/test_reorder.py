import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models import Forecast, MovementType, Product, ProductSupplier, StockMovement, Supplier
from app.services.reorder import current_stock, get_reorder_recommendation
from tests.helpers import register


async def _make_tenant_product(
    db_engine: AsyncEngine, client, sku: str = "A1"
) -> tuple[uuid.UUID, uuid.UUID]:
    user = await register(client, "Shop A", f"{sku.lower()}@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        product = Product(tenant_id=tenant_id, sku=sku, name=sku, current_price=5.0)
        session.add(product)
        await session.flush()
        product_id = product.id
        await session.commit()
    return tenant_id, product_id


async def _add_supplier_link(
    db_engine: AsyncEngine,
    tenant_id: uuid.UUID,
    product_id: uuid.UUID,
    lead_time_mean: float = 4.0,
    lead_time_std: float = 1.0,
    moq: int = 10,
    pack_size: int = 12,
) -> None:
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        supplier = Supplier(tenant_id=tenant_id, name="Test Supplier")
        session.add(supplier)
        await session.flush()
        session.add(
            ProductSupplier(
                tenant_id=tenant_id,
                product_id=product_id,
                supplier_id=supplier.id,
                unit_cost=1.0,
                lead_time_days_mean=lead_time_mean,
                lead_time_days_std=lead_time_std,
                moq=moq,
                pack_size=pack_size,
            )
        )
        await session.commit()


async def _add_stock_movement(
    db_engine: AsyncEngine, tenant_id: uuid.UUID, product_id: uuid.UUID, quantity: int
) -> None:
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        session.add(
            StockMovement(
                tenant_id=tenant_id,
                product_id=product_id,
                movement_type=MovementType.RECEIPT if quantity > 0 else MovementType.SALE,
                quantity=quantity,
                occurred_at=datetime.now(UTC),
            )
        )
        await session.commit()


async def _add_forecast_days(
    db_engine: AsyncEngine,
    tenant_id: uuid.UUID,
    product_id: uuid.UUID,
    upper_bounds: list[float],
    model_version: int = 1,
) -> None:
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    generated_at = datetime.now(UTC)
    async with maker() as session:
        for i, ub in enumerate(upper_bounds):
            session.add(
                Forecast(
                    tenant_id=tenant_id,
                    product_id=product_id,
                    target_date=date(2024, 1, 1 + i),
                    point_estimate=ub * 0.6,
                    upper_bound=ub,
                    model_version=model_version,
                    generated_at=generated_at,
                )
            )
        await session.commit()


async def test_current_stock_sums_receipts_and_sales(client, db_engine: AsyncEngine) -> None:
    tenant_id, product_id = await _make_tenant_product(db_engine, client)
    await _add_stock_movement(db_engine, tenant_id, product_id, 100)
    await _add_stock_movement(db_engine, tenant_id, product_id, -30)
    await _add_stock_movement(db_engine, tenant_id, product_id, -10)

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        stock = await current_stock(session, product_id)
    assert stock == 60


async def test_reorder_point_sums_upper_bound_over_the_lead_time_window(
    client, db_engine: AsyncEngine
) -> None:
    tenant_id, product_id = await _make_tenant_product(db_engine, client)
    await _add_supplier_link(
        db_engine, tenant_id, product_id, lead_time_mean=4.0, lead_time_std=1.0
    )
    await _add_stock_movement(db_engine, tenant_id, product_id, 200)
    # window = ceil(4 + 1) = 5 days; only the first 5 of these should count
    await _add_forecast_days(db_engine, tenant_id, product_id, [10, 10, 10, 10, 10, 999, 999])

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        rec = await get_reorder_recommendation(session, product_id)

    assert rec.lead_time_window_days == 5
    assert rec.reorder_point == 50.0


async def test_no_reorder_when_stock_covers_the_reorder_point(
    client, db_engine: AsyncEngine
) -> None:
    tenant_id, product_id = await _make_tenant_product(db_engine, client)
    await _add_supplier_link(
        db_engine, tenant_id, product_id, lead_time_mean=2.0, lead_time_std=0.0
    )
    await _add_stock_movement(db_engine, tenant_id, product_id, 100)
    await _add_forecast_days(db_engine, tenant_id, product_id, [10, 10])

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        rec = await get_reorder_recommendation(session, product_id)

    assert rec.should_reorder is False
    assert rec.order_quantity == 0


async def test_order_quantity_rounds_up_to_pack_size_and_respects_moq(
    client, db_engine: AsyncEngine
) -> None:
    tenant_id, product_id = await _make_tenant_product(db_engine, client)
    await _add_supplier_link(
        db_engine,
        tenant_id,
        product_id,
        lead_time_mean=1.0,
        lead_time_std=0.0,
        moq=50,
        pack_size=12,
    )
    await _add_stock_movement(db_engine, tenant_id, product_id, 0)
    await _add_forecast_days(db_engine, tenant_id, product_id, [10])

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        rec = await get_reorder_recommendation(session, product_id)

    # raw need = 10, rounds to 1 pack of 12 = 12, but MOQ is 50 -> 50
    assert rec.order_quantity == 50


async def test_order_quantity_uses_pack_size_when_above_moq(client, db_engine: AsyncEngine) -> None:
    tenant_id, product_id = await _make_tenant_product(db_engine, client)
    await _add_supplier_link(
        db_engine,
        tenant_id,
        product_id,
        lead_time_mean=1.0,
        lead_time_std=0.0,
        moq=10,
        pack_size=12,
    )
    await _add_stock_movement(db_engine, tenant_id, product_id, 0)
    await _add_forecast_days(db_engine, tenant_id, product_id, [25])

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        rec = await get_reorder_recommendation(session, product_id)

    # raw need = 25, ceil(25/12) = 3 packs * 12 = 36, above MOQ of 10 -> 36
    assert rec.order_quantity == 36


async def test_raises_when_no_supplier_link(client, db_engine: AsyncEngine) -> None:
    tenant_id, product_id = await _make_tenant_product(db_engine, client)
    await _add_forecast_days(db_engine, tenant_id, product_id, [10])

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        with pytest.raises(ValueError, match="no supplier link"):
            await get_reorder_recommendation(session, product_id)


async def test_raises_when_no_forecast(client, db_engine: AsyncEngine) -> None:
    tenant_id, product_id = await _make_tenant_product(db_engine, client)
    await _add_supplier_link(db_engine, tenant_id, product_id)

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        with pytest.raises(ValueError, match="no forecast"):
            await get_reorder_recommendation(session, product_id)


async def test_raises_when_lead_time_exceeds_forecast_horizon(
    client, db_engine: AsyncEngine
) -> None:
    tenant_id, product_id = await _make_tenant_product(db_engine, client)
    await _add_supplier_link(
        db_engine, tenant_id, product_id, lead_time_mean=30.0, lead_time_std=0.0
    )
    await _add_forecast_days(db_engine, tenant_id, product_id, [10])

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        with pytest.raises(ValueError, match="exceeds the"):
            await get_reorder_recommendation(session, product_id)


async def test_only_the_latest_forecast_run_is_used(client, db_engine: AsyncEngine) -> None:
    tenant_id, product_id = await _make_tenant_product(db_engine, client)
    await _add_supplier_link(
        db_engine, tenant_id, product_id, lead_time_mean=1.0, lead_time_std=0.0
    )
    await _add_stock_movement(db_engine, tenant_id, product_id, 0)
    await _add_forecast_days(db_engine, tenant_id, product_id, [10], model_version=1)
    await _add_forecast_days(db_engine, tenant_id, product_id, [999], model_version=2)

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        rec = await get_reorder_recommendation(session, product_id)

    assert rec.reorder_point == 999.0
