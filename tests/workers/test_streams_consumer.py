import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import settings
from app.db.models import MovementType, Product, StockMovement
from tests.helpers import register
from workers.stream_consumer import (
    DEAD_LETTER_STREAM,
    MAX_DELIVERIES,
    decode_fields,
    handle_entry,
    move_to_dead_letter,
    process_event,
)


async def test_move_to_dead_letter_writes_fields_and_reason_then_acks() -> None:
    redis = Redis.from_url(settings.redis_url)
    stream, group = "test-dlq-source", "test-dlq-group"
    await redis.delete(stream, DEAD_LETTER_STREAM)
    try:
        await redis.xgroup_create(stream, group, id="0", mkstream=True)
        entry_id = await redis.xadd(stream, {"event_id": "abc", "quantity": "bad"})
        await redis.xreadgroup(group, "c1", {stream: ">"}, count=1)

        with (
            patch("workers.stream_consumer.STREAM_NAME", stream),
            patch("workers.stream_consumer.GROUP_NAME", group),
        ):
            await move_to_dead_letter(
                redis, entry_id, {"event_id": "abc", "quantity": "bad"}, "bad quantity"
            )

        dead_entries = await redis.xrange(DEAD_LETTER_STREAM, "-", "+")
        assert len(dead_entries) == 1
        fields = {k.decode(): v.decode() for k, v in dead_entries[0][1].items()}
        assert fields["event_id"] == "abc"
        assert fields["failure_reason"] == "bad quantity"

        pending = await redis.xpending(stream, group)
        assert pending["pending"] == 0
    finally:
        await redis.delete(stream, DEAD_LETTER_STREAM)
        await redis.aclose()


async def test_handle_entry_dead_letters_after_max_deliveries() -> None:
    redis = AsyncMock()
    redis.xack = AsyncMock()
    redis.xadd = AsyncMock()

    with patch("workers.stream_consumer.delivery_count", AsyncMock(return_value=MAX_DELIVERIES)):
        with patch(
            "workers.stream_consumer.process_event", AsyncMock(side_effect=ValueError("boom"))
        ):
            await handle_entry(redis, None, b"1-0", {b"event_id": b"x", b"quantity": b"1"})

    redis.xadd.assert_awaited_once()
    redis.xack.assert_awaited_once()


async def test_handle_entry_does_not_dead_letter_before_max_deliveries() -> None:
    redis = AsyncMock()
    redis.xack = AsyncMock()
    redis.xadd = AsyncMock()

    with patch("workers.stream_consumer.delivery_count", AsyncMock(return_value=1)):
        with patch(
            "workers.stream_consumer.process_event", AsyncMock(side_effect=ValueError("boom"))
        ):
            await handle_entry(redis, None, b"1-0", {b"event_id": b"x", b"quantity": b"1"})

    redis.xadd.assert_not_awaited()
    redis.xack.assert_not_awaited()


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
