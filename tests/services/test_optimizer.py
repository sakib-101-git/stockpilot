import uuid
from datetime import UTC, date, datetime

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models import Forecast, MovementType, Product, ProductSupplier, StockMovement, Supplier
from app.services.optimizer import optimize_budget
from tests.helpers import register


async def _make_tenant(db_engine: AsyncEngine, client) -> uuid.UUID:
    user = await register(client, "Shop A", f"opt-{uuid.uuid4().hex[:8]}@example.com")
    return uuid.UUID(user["tenant_id"])


async def _make_product_with_reorder_need(
    db_engine: AsyncEngine,
    tenant_id: uuid.UUID,
    sku: str,
    stock: int,
    upper_bound: float,
    unit_cost: float,
    pack_size: int = 1,
    moq: int = 1,
) -> uuid.UUID:
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        product = Product(tenant_id=tenant_id, sku=sku, name=sku, current_price=unit_cost * 2)
        session.add(product)
        await session.flush()
        product_id = product.id

        supplier = Supplier(tenant_id=tenant_id, name=f"Supplier-{sku}")
        session.add(supplier)
        await session.flush()
        session.add(
            ProductSupplier(
                tenant_id=tenant_id,
                product_id=product_id,
                supplier_id=supplier.id,
                unit_cost=unit_cost,
                lead_time_days_mean=1.0,
                lead_time_days_std=0.0,
                moq=moq,
                pack_size=pack_size,
            )
        )
        if stock != 0:
            session.add(
                StockMovement(
                    tenant_id=tenant_id,
                    product_id=product_id,
                    movement_type=MovementType.RECEIPT if stock > 0 else MovementType.SALE,
                    quantity=stock,
                    occurred_at=datetime.now(UTC),
                )
            )
        session.add(
            Forecast(
                tenant_id=tenant_id,
                product_id=product_id,
                target_date=date(2024, 1, 1),
                point_estimate=upper_bound * 0.6,
                upper_bound=upper_bound,
                model_version=1,
                generated_at=datetime.now(UTC),
            )
        )
        await session.commit()
    return product_id


async def test_optimizer_stays_within_budget(client, db_engine: AsyncEngine) -> None:
    tenant_id = await _make_tenant(db_engine, client)
    await _make_product_with_reorder_need(
        db_engine, tenant_id, "A1", stock=0, upper_bound=100, unit_cost=10.0
    )
    await _make_product_with_reorder_need(
        db_engine, tenant_id, "B1", stock=0, upper_bound=100, unit_cost=10.0
    )

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        result = await optimize_budget(session, tenant_id, budget=1000.0)

    assert result.total_cost <= result.budget


async def test_optimizer_skips_products_that_dont_need_reordering(
    client, db_engine: AsyncEngine
) -> None:
    tenant_id = await _make_tenant(db_engine, client)
    await _make_product_with_reorder_need(
        db_engine, tenant_id, "A1", stock=1000, upper_bound=10, unit_cost=1.0
    )

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        result = await optimize_budget(session, tenant_id, budget=10000.0)

    assert result.orders == []
    assert result.skipped_product_ids == []


async def test_optimizer_prefers_higher_priority_when_budget_is_tight(
    client, db_engine: AsyncEngine
) -> None:
    tenant_id = await _make_tenant(db_engine, client)
    urgent = await _make_product_with_reorder_need(
        db_engine, tenant_id, "A1", stock=0, upper_bound=100, unit_cost=10.0
    )
    calm = await _make_product_with_reorder_need(
        db_engine, tenant_id, "B1", stock=90, upper_bound=100, unit_cost=10.0
    )

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        result = await optimize_budget(session, tenant_id, budget=1050.0)

    chosen_ids = {o.product_id for o in result.orders}
    assert urgent in chosen_ids
    assert calm not in chosen_ids


async def test_optimizer_with_zero_budget_orders_nothing(client, db_engine: AsyncEngine) -> None:
    tenant_id = await _make_tenant(db_engine, client)
    await _make_product_with_reorder_need(
        db_engine, tenant_id, "A1", stock=0, upper_bound=100, unit_cost=10.0
    )

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        result = await optimize_budget(session, tenant_id, budget=0.0)

    assert result.orders == []
    assert result.total_cost == 0.0


async def test_optimizer_only_considers_the_given_tenant(client, db_engine: AsyncEngine) -> None:
    tenant_a = await _make_tenant(db_engine, client)
    tenant_b = await _make_tenant(db_engine, client)
    await _make_product_with_reorder_need(
        db_engine, tenant_a, "A1", stock=0, upper_bound=100, unit_cost=10.0
    )
    await _make_product_with_reorder_need(
        db_engine, tenant_b, "B1", stock=0, upper_bound=100, unit_cost=10.0
    )

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        result_a = await optimize_budget(session, tenant_a, budget=10000.0)

    assert len(result_a.orders) == 1
    assert result_a.orders[0].sku == "A1"
