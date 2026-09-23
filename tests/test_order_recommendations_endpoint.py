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

        supplier = Supplier(tenant_id=tenant_id, name=f"Supplier-{sku}")
        session.add(supplier)
        await session.flush()
        session.add(
            ProductSupplier(
                tenant_id=tenant_id,
                product_id=product_id,
                supplier_id=supplier.id,
                unit_cost=2.0,
                lead_time_days_mean=1.0,
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


async def test_generate_recommendations_returns_pending_rows(
    client, db_engine: AsyncEngine
) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    await _make_reorderable_product(db_engine, tenant_id)

    headers = await login_headers(client, "a@example.com")
    response = await client.post(
        "/recommendations/generate", json={"budget": 1000}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["status"] == "pending"


async def test_generate_recommendations_requires_owner_role(client, db_engine: AsyncEngine) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    await _make_reorderable_product(db_engine, tenant_id)

    owner_headers = await login_headers(client, "a@example.com")
    staff_response = await client.post(
        "/users",
        json={"email": "staff@example.com", "password": "correct-horse-9"},
        headers=owner_headers,
    )
    assert staff_response.status_code in (200, 201)
    staff_headers = await login_headers(client, "staff@example.com")

    response = await client.post(
        "/recommendations/generate", json={"budget": 1000}, headers=staff_headers
    )
    assert response.status_code == 403


async def test_generate_recommendations_rejects_zero_budget(client, db_engine: AsyncEngine) -> None:
    await register(client, "Shop A", "a@example.com")
    headers = await login_headers(client, "a@example.com")

    response = await client.post("/recommendations/generate", json={"budget": 0}, headers=headers)
    assert response.status_code == 422


async def test_generate_recommendations_without_a_token_is_401(client) -> None:
    response = await client.post("/recommendations/generate", json={"budget": 1000})
    assert response.status_code == 401


async def test_get_pending_recommendations_staff_can_view(client, db_engine: AsyncEngine) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    await _make_reorderable_product(db_engine, tenant_id)

    owner_headers = await login_headers(client, "a@example.com")
    await client.post("/recommendations/generate", json={"budget": 1000}, headers=owner_headers)
    await client.post(
        "/users",
        json={"email": "staff2@example.com", "password": "correct-horse-9"},
        headers=owner_headers,
    )
    staff_headers = await login_headers(client, "staff2@example.com")

    response = await client.get("/recommendations/pending", headers=staff_headers)
    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_approve_then_approve_again_is_409(client, db_engine: AsyncEngine) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    await _make_reorderable_product(db_engine, tenant_id)

    headers = await login_headers(client, "a@example.com")
    generated = await client.post(
        "/recommendations/generate", json={"budget": 1000}, headers=headers
    )
    rec_id = generated.json()[0]["id"]

    first = await client.post(f"/recommendations/{rec_id}/approve", headers=headers)
    assert first.status_code == 200
    assert first.json()["status"] == "approved"

    second = await client.post(f"/recommendations/{rec_id}/approve", headers=headers)
    assert second.status_code == 409


async def test_approve_a_nonexistent_recommendation_is_404(client, db_engine: AsyncEngine) -> None:
    await register(client, "Shop A", "a@example.com")
    headers = await login_headers(client, "a@example.com")

    response = await client.post(f"/recommendations/{uuid.uuid4()}/approve", headers=headers)
    assert response.status_code == 404


async def test_edit_sets_the_provided_quantity(client, db_engine: AsyncEngine) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    await _make_reorderable_product(db_engine, tenant_id)

    headers = await login_headers(client, "a@example.com")
    generated = await client.post(
        "/recommendations/generate", json={"budget": 1000}, headers=headers
    )
    rec_id = generated.json()[0]["id"]

    response = await client.post(
        f"/recommendations/{rec_id}/edit", json={"new_quantity": 77}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "edited"
    assert response.json()["final_quantity"] == 77


async def test_reject_sets_status_rejected(client, db_engine: AsyncEngine) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    await _make_reorderable_product(db_engine, tenant_id)

    headers = await login_headers(client, "a@example.com")
    generated = await client.post(
        "/recommendations/generate", json={"budget": 1000}, headers=headers
    )
    rec_id = generated.json()[0]["id"]

    response = await client.post(f"/recommendations/{rec_id}/reject", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


async def test_another_tenants_recommendation_is_404_not_leaked(
    client, db_engine: AsyncEngine
) -> None:
    user_a = await register(client, "Shop A", "a@example.com")
    tenant_a = uuid.UUID(user_a["tenant_id"])
    await _make_reorderable_product(db_engine, tenant_a)

    headers_a = await login_headers(client, "a@example.com")
    generated = await client.post(
        "/recommendations/generate", json={"budget": 1000}, headers=headers_a
    )
    rec_id = generated.json()[0]["id"]

    await register(client, "Shop B", "b@example.com")
    headers_b = await login_headers(client, "b@example.com")

    response = await client.post(f"/recommendations/{rec_id}/approve", headers=headers_b)
    assert response.status_code == 404
