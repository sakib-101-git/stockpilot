"""Redis Streams consumer: turns sales events into stock_movements rows.

Idempotent on event_id (stored in StockMovement.reference), so a redelivered
event is not double-counted. Retry and dead-letter handling for genuinely
failing events are not yet implemented here — see the next step.

Run continuously: uv run python -m workers.stream_consumer
"""

import asyncio
import uuid
from datetime import datetime

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.models import MovementType, StockMovement

STREAM_NAME = "sales-events"
GROUP_NAME = "stock-consumers"


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

    Raises ValueError/KeyError for a malformed event (missing or unparseable
    field) rather than silently doing nothing — the caller decides what a
    malformed event means for retry/dead-letter purposes.
    """
    tenant_id = uuid.UUID(fields["tenant_id"])
    product_id = uuid.UUID(fields["product_id"])
    quantity = int(fields["quantity"])
    event_id = fields["event_id"]
    occurred_at = datetime.fromisoformat(fields["occurred_at"])

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


async def run_consumer(consumer_name: str = "consumer-1") -> None:
    """Read events forever, write each one, ack on success.

    On failure: logs and does NOT ack, so the entry stays pending. There is
    no reclaim/retry logic yet — a failed entry sits pending indefinitely
    until the next step adds XAUTOCLAIM-based redelivery and a dead-letter
    stream for entries that keep failing.
    """
    redis = Redis.from_url(settings.redis_url)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    await ensure_group(redis)

    try:
        while True:
            result = await redis.xreadgroup(
                GROUP_NAME, consumer_name, {STREAM_NAME: ">"}, count=10, block=5000
            )
            if not result:
                continue
            _, entries = result[0]
            for entry_id, raw_fields in entries:
                fields = decode_fields(raw_fields)
                try:
                    async with session_maker() as session:
                        await process_event(session, fields)
                    await redis.xack(STREAM_NAME, GROUP_NAME, entry_id)
                    print(f"processed {entry_id.decode()}: {fields.get('event_id')}")
                except Exception as exc:
                    print(f"FAILED {entry_id.decode()}: {exc} (left pending, no retry yet)")
    finally:
        await engine.dispose()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(run_consumer())
