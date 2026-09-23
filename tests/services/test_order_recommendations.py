import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models import Forecast, Product, ProductSupplier, Supplier
from app.services.order_recommendations import (
    approve_recommendation,
    edit_recommendation,
    generate_recommendations,
    list_pending_recommendations,
    reject_recommendation,
)
from tests.helpers import register


async def _make_tenant_with_user(db_engine: AsyncEngine, client) -> tuple[uuid.UUID, uuid.UUID]:
    user = await register(client, "Shop A", f"rec-{uuid.uuid4().hex[:8]}@example.com")
    return uuid.UUID(user["tenant_id"]), uuid.UUID(user["id"])


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


async def test_generate_recommendations_creates_pending_rows(
    client, db_engine: AsyncEngine
) -> None:
    tenant_id, _ = await _make_tenant_with_user(db_engine, client)
    await _make_reorderable_product(db_engine, tenant_id)

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        rows = await generate_recommendations(session, tenant_id, budget=1000.0)

    assert len(rows) == 1
    assert rows[0].status == "pending"
    assert rows[0].final_quantity is None


async def test_approve_sets_final_quantity_to_suggested(client, db_engine: AsyncEngine) -> None:
    tenant_id, user_id = await _make_tenant_with_user(db_engine, client)
    await _make_reorderable_product(db_engine, tenant_id)

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        rows = await generate_recommendations(session, tenant_id, budget=1000.0)
    async with maker() as session:
        approved = await approve_recommendation(session, tenant_id, rows[0].id, user_id)

    assert approved.status == "approved"
    assert approved.final_quantity == approved.suggested_quantity
    assert approved.decided_by == user_id
    assert approved.decided_at is not None


async def test_edit_uses_the_provided_quantity_not_the_suggested_one(
    client, db_engine: AsyncEngine
) -> None:
    tenant_id, user_id = await _make_tenant_with_user(db_engine, client)
    await _make_reorderable_product(db_engine, tenant_id)

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        rows = await generate_recommendations(session, tenant_id, budget=1000.0)
    async with maker() as session:
        edited = await edit_recommendation(session, tenant_id, rows[0].id, user_id, new_quantity=42)

    assert edited.status == "edited"
    assert edited.final_quantity == 42
    assert edited.final_quantity != edited.suggested_quantity


async def test_reject_leaves_final_quantity_none(client, db_engine: AsyncEngine) -> None:
    tenant_id, user_id = await _make_tenant_with_user(db_engine, client)
    await _make_reorderable_product(db_engine, tenant_id)

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        rows = await generate_recommendations(session, tenant_id, budget=1000.0)
    async with maker() as session:
        rejected = await reject_recommendation(session, tenant_id, rows[0].id, user_id)

    assert rejected.status == "rejected"
    assert rejected.final_quantity is None


async def test_cannot_act_on_an_already_decided_recommendation(
    client, db_engine: AsyncEngine
) -> None:
    tenant_id, user_id = await _make_tenant_with_user(db_engine, client)
    await _make_reorderable_product(db_engine, tenant_id)

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        rows = await generate_recommendations(session, tenant_id, budget=1000.0)
    async with maker() as session:
        await approve_recommendation(session, tenant_id, rows[0].id, user_id)

    async with maker() as session:
        with pytest.raises(ValueError, match="already approved"):
            await approve_recommendation(session, tenant_id, rows[0].id, user_id)

    async with maker() as session:
        with pytest.raises(ValueError, match="already approved"):
            await reject_recommendation(session, tenant_id, rows[0].id, user_id)


async def test_edit_rejects_a_negative_quantity(client, db_engine: AsyncEngine) -> None:
    tenant_id, user_id = await _make_tenant_with_user(db_engine, client)
    await _make_reorderable_product(db_engine, tenant_id)

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        rows = await generate_recommendations(session, tenant_id, budget=1000.0)
    async with maker() as session:
        with pytest.raises(ValueError, match="negative"):
            await edit_recommendation(session, tenant_id, rows[0].id, user_id, new_quantity=-5)


async def test_list_pending_only_shows_pending_rows(client, db_engine: AsyncEngine) -> None:
    tenant_id, user_id = await _make_tenant_with_user(db_engine, client)
    await _make_reorderable_product(db_engine, tenant_id, "A1")
    await _make_reorderable_product(db_engine, tenant_id, "B1")

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        rows = await generate_recommendations(session, tenant_id, budget=1000.0)
    async with maker() as session:
        await approve_recommendation(session, tenant_id, rows[0].id, user_id)

    async with maker() as session:
        pending = await list_pending_recommendations(session, tenant_id)

    assert len(pending) == 1
    assert pending[0].id == rows[1].id


async def test_acting_on_another_tenants_recommendation_raises(
    client, db_engine: AsyncEngine
) -> None:
    tenant_a, user_a = await _make_tenant_with_user(db_engine, client)
    tenant_b, user_b = await _make_tenant_with_user(db_engine, client)
    await _make_reorderable_product(db_engine, tenant_a)

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        rows = await generate_recommendations(session, tenant_a, budget=1000.0)

    async with maker() as session:
        with pytest.raises(ValueError, match="not found"):
            await approve_recommendation(session, tenant_b, rows[0].id, user_b)
