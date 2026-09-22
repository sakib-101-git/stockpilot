"""Replay M5 sales history onto the sales-events Redis Stream, oldest first.

Simulates a live POS feed for demo and consumer-testing purposes. This is
NOT real-time data — see docs/decisions/0007-synthetic-supply-data.md and
the Week 4 decision note for what this does and does not represent.

Usage: uv run python -m scripts.synth.replay [--delay SECONDS] [--limit N]
"""

import argparse
import asyncio
import time
import uuid
from pathlib import Path

import pandas as pd
from redis.asyncio import Redis
from sqlalchemy import select, text

from app.core.config import settings
from app.db.models import Product, Tenant
from app.db.session import SessionLocal

STREAM_NAME = "sales-events"


async def _tenant_product_lookup() -> dict[tuple[str, str], tuple[str, str]]:
    """Maps (store_id, sku) -> (tenant_id, product_id) for every seeded tenant."""
    lookup: dict[tuple[str, str], tuple[str, str]] = {}
    async with SessionLocal() as session:
        tenants = (await session.execute(select(Tenant))).scalars().all()
        for tenant in tenants:
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
                {"tenant_id": str(tenant.id)},
            )
            store_id = tenant.name.split(" ")[0]
            products = (
                (await session.execute(select(Product).where(Product.tenant_id == tenant.id)))
                .scalars()
                .all()
            )
            for product in products:
                lookup[(store_id, product.sku)] = (str(tenant.id), str(product.id))
    return lookup


async def replay(delay_seconds: float, limit: int | None) -> None:
    root = Path(__file__).resolve().parents[2]
    sales = pd.read_parquet(root / "data" / "processed" / "sales.parquet")
    sales = sales[sales["units"] > 0].sort_values("date")
    if limit:
        sales = sales.head(limit)

    lookup = await _tenant_product_lookup()
    redis = Redis.from_url(settings.redis_url)

    pushed, skipped = 0, 0
    try:
        for row in sales.itertuples():
            key = (row.store_id, row.item_id)
            if key not in lookup:
                skipped += 1
                continue

            tenant_id, product_id = lookup[key]
            await redis.xadd(
                STREAM_NAME,
                {
                    "event_id": str(uuid.uuid4()),
                    "tenant_id": tenant_id,
                    "product_id": product_id,
                    "quantity": str(int(row.units)),
                    "occurred_at": row.date.isoformat(),
                },
            )
            pushed += 1
            if pushed % 500 == 0:
                print(f"pushed {pushed} events...")
            if delay_seconds:
                time.sleep(delay_seconds)
    finally:
        await redis.aclose()

    print(f"done: {pushed} pushed, {skipped} skipped (no matching tenant/product)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay", type=float, default=0.0, help="seconds between events")
    parser.add_argument("--limit", type=int, default=None, help="max sales rows to replay")
    args = parser.parse_args()
    asyncio.run(replay(args.delay, args.limit))


if __name__ == "__main__":
    main()
