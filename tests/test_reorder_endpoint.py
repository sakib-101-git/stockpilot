import uuid
from datetime import UTC, date, datetime

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models import Forecast, Product, ProductSupplier, Supplier
from tests.helpers import login_headers, register


async def _make_reorderable_product(
    db_engine: AsyncEngine, tenant_id: uuid.UUID, sku: str = "A1"
) -> uuid.UUID:
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        product = Product(tenant_id=tenant_id, sku=sku, name=sku, current_price=5.0)
        session.add(product)
        await session.flush()
        product_id = product.id

        supplier = Supplier(tenant_id=tenant_id, name="Supplier")
        session.add(supplier)
        await session.flush()
        session.add(
            ProductSupplier(
                tenant_id=tenant_id,
                product_id=product_id,
                supplier_id=supplier.id,
                unit_cost=2.0,
                lead_time_days_mean=2.0,
                lead_time_days_std=0.0,
                moq=1,
                pack_size=1,
            )
        )
        session.add(
            Forecast(
                tenant_id=tenant_id,
                product_id=product_id,
                target_date=date(2024, 1, 1),
                point_estimate=6.0,
                upper_bound=10.0,
                model_version=1,
                generated_at=datetime.now(UTC),
            )
        )
        await session.commit()
    return product_id


async def _make_product_without_supplier(
    db_engine: AsyncEngine, tenant_id: uuid.UUID, sku: str = "B1"
) -> uuid.UUID:
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        product = Product(tenant_id=tenant_id, sku=sku, name=sku, current_price=5.0)
        session.add(product)
        await session.commit()
        return product.id


async def test_get_product_reorder_returns_the_recommendation(client, db_engine) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    product_id = await _make_reorderable_product(db_engine, tenant_id)

    headers = await login_headers(client, "a@example.com")
    response = await client.get(f"/products/{product_id}/reorder", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["should_reorder"] is True
    assert body["lead_time_window_days"] == 2


async def test_get_product_reorder_without_supplier_link_is_422(client, db_engine) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    product_id = await _make_product_without_supplier(db_engine, tenant_id)

    headers = await login_headers(client, "a@example.com")
    response = await client.get(f"/products/{product_id}/reorder", headers=headers)

    assert response.status_code == 422


async def test_get_product_reorder_for_another_tenants_product_is_404(client, db_engine) -> None:
    user_a = await register(client, "Shop A", "a@example.com")
    tenant_a = uuid.UUID(user_a["tenant_id"])
    product_id = await _make_reorderable_product(db_engine, tenant_a)
    await register(client, "Shop B", "b@example.com")

    headers_b = await login_headers(client, "b@example.com")
    response = await client.get(f"/products/{product_id}/reorder", headers=headers_b)

    assert response.status_code == 404


async def test_get_product_reorder_without_a_token_is_401(client) -> None:
    response = await client.get(f"/products/{uuid.uuid4()}/reorder")
    assert response.status_code == 401


async def test_optimize_budget_returns_orders_within_budget(client, db_engine) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    await _make_reorderable_product(db_engine, tenant_id, "A1")

    headers = await login_headers(client, "a@example.com")
    response = await client.get("/optimize-budget?budget=1000", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total_cost"] <= body["budget"]


async def test_optimize_budget_rejects_zero_budget(client, db_engine) -> None:
    await register(client, "Shop A", "a@example.com")
    headers = await login_headers(client, "a@example.com")

    response = await client.get("/optimize-budget?budget=0", headers=headers)

    assert response.status_code == 422


async def test_optimize_budget_requires_the_budget_parameter(client, db_engine) -> None:
    await register(client, "Shop A", "a@example.com")
    headers = await login_headers(client, "a@example.com")

    response = await client.get("/optimize-budget", headers=headers)

    assert response.status_code == 422


async def test_optimize_budget_only_considers_the_callers_tenant(client, db_engine) -> None:
    user_a = await register(client, "Shop A", "a@example.com")
    tenant_a = uuid.UUID(user_a["tenant_id"])
    await _make_reorderable_product(db_engine, tenant_a, "A1")
    await register(client, "Shop B", "b@example.com")

    headers_b = await login_headers(client, "b@example.com")
    response = await client.get("/optimize-budget?budget=1000", headers=headers_b)

    assert response.status_code == 200
    assert response.json()["orders"] == []


async def test_optimize_budget_without_a_token_is_401(client) -> None:
    response = await client.get("/optimize-budget?budget=100")
    assert response.status_code == 401
