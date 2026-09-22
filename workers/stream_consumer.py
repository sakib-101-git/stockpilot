"""Redis Streams consumer: turns sales events into stock_movements rows.

Idempotent on event_id (stored in StockMovement.reference), so a redelivered
event is not double-counted. Failed events are retried up to MAX_DELIVERIES
times (tracked via Redis's own per-entry delivery count), then moved to the
sales-events-dead stream and acked off the main stream, so a permanently
failing event cannot block progress forever.

Run continuously: uv run python -m workers.stream_consumer
"""

import asyncio
import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.models import MovementType, StockMovement

STREAM_NAME = "sales-events"
DEAD_LETTER_STREAM = "sales-events-dead"
GROUP_NAME = "stock-consumers"
MAX_DELIVERIES = 3
CLAIM_IDLE_MS = 30_000  # reclaim entries pending longer than this


async def ensure_group(redis: Redis, stream: str = STREAM_NAME, group: str = GROUP_NAME) -> None:
    """Create the consumer group if it doesn't exist yet. Safe to call every startup."""
    try:
        await redis.xgroup_create(stream, group, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def decode_fields(raw: dict[bytes, bytes]) -> dict[str, str]:
    """Redis returns every field as bytes; decode once, at the boundary."""
    return {k.decode(): v.decode() for k, v in raw.items()}


async def already_processed(session: AsyncSession, tenant_id: uuid.UUID, event_id: str) -> bool:
    result = await session.execute(
        select(StockMovement.id).where(
            StockMovement.tenant_id == tenant_id,
            StockMovement.reference == f"event:{event_id}",
        )
    )
    return result.scalar_one_or_none() is not None


async def process_event(session: AsyncSession, fields: dict[str, str]) -> None:
    """Write one sale as a negative StockMovement. Idempotent on event_id.

    Raises for a malformed or otherwise unprocessable event, rather than
    silently doing nothing. The caller decides retry/dead-letter behavior.
    """
    tenant_id = uuid.UUID(fields["tenant_id"])
    product_id = uuid.UUID(fields["product_id"])
    quantity = int(fields["quantity"])
    event_id = fields["event_id"]
    occurred_at = datetime.fromisoformat(fields["occurred_at"]).replace(tzinfo=UTC)

    await session.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )

    if await already_processed(session, tenant_id, event_id):
        return

    session.add(
        StockMovement(
            tenant_id=tenant_id,
            product_id=product_id,
            movement_type=MovementType.SALE,
            quantity=-quantity,
            reference=f"event:{event_id}",
            occurred_at=occurred_at,
        )
    )
    await session.commit()


async def delivery_count(redis: Redis, entry_id: bytes) -> int:
    """How many times this entry has been claimed, per Redis's own tracking."""
    detail = await redis.xpending_range(
        STREAM_NAME, GROUP_NAME, min=entry_id, max=entry_id, count=1
    )
    if not detail:
        return 0
    return detail[0]["times_delivered"]


async def move_to_dead_letter(
    redis: Redis, entry_id: bytes, fields: dict[str, str], reason: str
) -> None:
    await redis.xadd(DEAD_LETTER_STREAM, {**fields, "failure_reason": reason})
    await redis.xack(STREAM_NAME, GROUP_NAME, entry_id)


async def handle_entry(
    redis: Redis, session_maker, entry_id: bytes, raw_fields: dict[bytes, bytes]
) -> None:
    fields = decode_fields(raw_fields)
    try:
        async with session_maker() as session:
            await process_event(session, fields)
        await redis.xack(STREAM_NAME, GROUP_NAME, entry_id)
        print(f"processed {entry_id.decode()}: {fields.get('event_id')}")
    except Exception as exc:
        deliveries = await delivery_count(redis, entry_id)
        if deliveries >= MAX_DELIVERIES:
            await move_to_dead_letter(redis, entry_id, fields, str(exc))
            print(f"DEAD-LETTERED {entry_id.decode()} after {deliveries} attempts: {exc}")
        else:
            print(f"FAILED {entry_id.decode()} (attempt {deliveries}): {exc} — will retry")


async def run_consumer(consumer_name: str = "consumer-1") -> None:
    redis = Redis.from_url(settings.redis_url)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    await ensure_group(redis)

    try:
        while True:
            # First, reclaim any entries stuck pending from a crashed/slow consumer.
            _, claimed, _ = await redis.xautoclaim(
                STREAM_NAME, GROUP_NAME, consumer_name, min_idle_time=CLAIM_IDLE_MS, start_id="0"
            )
            for entry_id, raw_fields in claimed:
                await handle_entry(redis, session_maker, entry_id, raw_fields)

            # Then read genuinely new entries.
            result = await redis.xreadgroup(
                GROUP_NAME, consumer_name, {STREAM_NAME: ">"}, count=10, block=5000
            )
            if not result:
                continue
            _, entries = result[0]
            for entry_id, raw_fields in entries:
                await handle_entry(redis, session_maker, entry_id, raw_fields)
    finally:
        await engine.dispose()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(run_consumer())
