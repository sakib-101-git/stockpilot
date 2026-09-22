import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models import MovementType, Product, StockMovement
from tests.helpers import register
from workers.stream_consumer import decode_fields, process_event


async def _make_product(db_engine: AsyncEngine, tenant_id: uuid.UUID, sku: str) -> uuid.UUID:
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        product = Product(tenant_id=tenant_id, sku=sku, name=sku)
        session.add(product)
        await session.commit()
        return product.id


def _fields(tenant_id, product_id, quantity=5, event_id=None) -> dict[str, str]:
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "tenant_id": str(tenant_id),
        "product_id": str(product_id),
        "quantity": str(quantity),
        "occurred_at": datetime.now(UTC).isoformat(),
    }


def test_decode_fields_converts_bytes_to_str() -> None:
    raw = {b"sku": b"A1", b"quantity": b"5"}
    assert decode_fields(raw) == {"sku": "A1", "quantity": "5"}


async def test_process_event_creates_a_negative_stock_movement(
    client, db_engine: AsyncEngine
) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    product_id = await _make_product(db_engine, tenant_id, "A1")

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        await process_event(session, _fields(tenant_id, product_id, quantity=7))

    async with maker() as session:
        result = await session.execute(
            select(StockMovement).where(StockMovement.tenant_id == tenant_id)
        )
        movements = result.scalars().all()
    assert len(movements) == 1
    assert movements[0].quantity == -7
    assert movements[0].movement_type == MovementType.SALE


async def test_process_event_is_idempotent_on_event_id(client, db_engine: AsyncEngine) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    product_id = await _make_product(db_engine, tenant_id, "A1")
    fields = _fields(tenant_id, product_id, event_id="repeat-me")

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        await process_event(session, fields)
    async with maker() as session:
        await process_event(session, fields)

    async with maker() as session:
        result = await session.execute(
            select(StockMovement).where(StockMovement.tenant_id == tenant_id)
        )
        movements = result.scalars().all()
    assert len(movements) == 1


async def test_process_event_is_scoped_to_the_correct_tenant(
    client, db_engine: AsyncEngine
) -> None:
    user_a = await register(client, "Shop A", "a@example.com")
    user_b = await register(client, "Shop B", "b@example.com")
    tenant_a, tenant_b = uuid.UUID(user_a["tenant_id"]), uuid.UUID(user_b["tenant_id"])
    product_a = await _make_product(db_engine, tenant_a, "A1")

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        await process_event(session, _fields(tenant_a, product_a))

    async with maker() as session:
        result_a = await session.execute(
            select(StockMovement).where(StockMovement.tenant_id == tenant_a)
        )
        result_b = await session.execute(
            select(StockMovement).where(StockMovement.tenant_id == tenant_b)
        )
    assert len(result_a.scalars().all()) == 1
    assert len(result_b.scalars().all()) == 0


async def test_process_event_rejects_a_malformed_quantity(client, db_engine: AsyncEngine) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    product_id = await _make_product(db_engine, tenant_id, "A1")
    fields = _fields(tenant_id, product_id)
    fields["quantity"] = "not-a-number"

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        with pytest.raises(ValueError):
            await process_event(session, fields)
