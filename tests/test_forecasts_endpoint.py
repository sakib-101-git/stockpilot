import uuid
from datetime import UTC, date, datetime

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models import Forecast, Product
from tests.helpers import login_headers, register


async def _add_product_with_forecast(
    db_engine: AsyncEngine, tenant_id: uuid.UUID, sku: str
) -> uuid.UUID:
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        product = Product(tenant_id=tenant_id, sku=sku, name=sku, current_price=1.0)
        session.add(product)
        await session.flush()
        for h in range(3):
            session.add(
                Forecast(
                    tenant_id=tenant_id,
                    product_id=product.id,
                    target_date=date(2024, 1, 1 + h),
                    point_estimate=1.0 + h,
                    upper_bound=2.0 + h,
                    model_version=1,
                )
            )
        await session.commit()
        return product.id


async def test_get_product_forecast_returns_the_latest_runs_rows(client, db_engine) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    product_id = await _add_product_with_forecast(db_engine, tenant_id, "A1")

    headers = await login_headers(client, "a@example.com")
    response = await client.get(f"/products/{product_id}/forecast", headers=headers)

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 3
    assert rows[0]["target_date"] == "2024-01-01"
    assert rows[0]["point_estimate"] == 1.0


async def test_get_product_forecast_uses_only_the_most_recent_run(client, db_engine) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    product_id = await _add_product_with_forecast(db_engine, tenant_id, "A1")

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        session.add(
            Forecast(
                tenant_id=tenant_id,
                product_id=product_id,
                target_date=date(2024, 2, 1),
                point_estimate=99.0,
                upper_bound=100.0,
                model_version=2,
                generated_at=datetime.now(UTC),
            )
        )
        await session.commit()

    headers = await login_headers(client, "a@example.com")
    response = await client.get(f"/products/{product_id}/forecast", headers=headers)

    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["model_version"] == 2
    assert rows[0]["point_estimate"] == 99.0


async def test_get_product_forecast_with_no_forecasts_yet_returns_empty_list(
    client, db_engine
) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        product = Product(tenant_id=tenant_id, sku="A1", name="A1", current_price=1.0)
        session.add(product)
        await session.commit()
        product_id = product.id

    headers = await login_headers(client, "a@example.com")
    response = await client.get(f"/products/{product_id}/forecast", headers=headers)

    assert response.status_code == 200
    assert response.json() == []


async def test_another_tenants_product_forecast_looks_like_it_does_not_exist(
    client, db_engine
) -> None:
    user_a = await register(client, "Shop A", "a@example.com")
    await register(client, "Shop B", "b@example.com")
    tenant_a = uuid.UUID(user_a["tenant_id"])
    product_id = await _add_product_with_forecast(db_engine, tenant_a, "A1")

    headers_b = await login_headers(client, "b@example.com")
    response = await client.get(f"/products/{product_id}/forecast", headers=headers_b)

    assert response.status_code == 404


async def test_product_forecast_without_a_token_is_401(client) -> None:
    response = await client.get(f"/products/{uuid.uuid4()}/forecast")
    assert response.status_code == 401


async def test_forecast_summary_returns_one_row_per_product(client, db_engine) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    await _add_product_with_forecast(db_engine, tenant_id, "A1")
    await _add_product_with_forecast(db_engine, tenant_id, "B1")

    headers = await login_headers(client, "a@example.com")
    response = await client.get("/forecasts/summary", headers=headers)

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    assert {r["sku"] for r in rows} == {"A1", "B1"}
    assert all(r["target_date"] == "2024-01-01" for r in rows)


async def test_forecast_summary_only_includes_the_callers_tenant(client, db_engine) -> None:
    user_a = await register(client, "Shop A", "a@example.com")
    await register(client, "Shop B", "b@example.com")
    tenant_a = uuid.UUID(user_a["tenant_id"])
    await _add_product_with_forecast(db_engine, tenant_a, "A1")

    headers_b = await login_headers(client, "b@example.com")
    response = await client.get("/forecasts/summary", headers=headers_b)

    assert response.status_code == 200
    assert response.json() == []


async def test_forecast_summary_without_a_token_is_401(client) -> None:
    response = await client.get("/forecasts/summary")
    assert response.status_code == 401
