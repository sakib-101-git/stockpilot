"""Bulk-load M5 sample products into their matching tenants.

Run once per environment, before scripts/synth/seed.py:
    uv run python -m scripts.synth.load_products

Matches tenants to M5 stores by the tenant's name (e.g. "CA_1 Store" -> "CA_1"),
the same convention scripts/synth/seed.py uses. A tenant whose name doesn't
start with a known store_id is skipped.
"""

import asyncio
from pathlib import Path

import pandas as pd
from sqlalchemy import select

from app.db.models import Tenant
from app.db.session import SessionLocal
from app.services.product_loader import load_products
from scripts.synth.generate import summarize_products


async def main() -> None:
    root = Path(__file__).resolve().parents[2]
    sales = pd.read_parquet(root / "data" / "processed" / "sales.parquet")
    products = summarize_products(sales)

    async with SessionLocal() as session:
        tenants = (await session.execute(select(Tenant))).scalars().all()
        print(f"found {len(tenants)} tenants")
        for tenant in tenants:
            store_id = tenant.name.split(" ")[0]
            store_products = products[products["store_id"] == store_id]
            if store_products.empty:
                print(f"  {tenant.name}: no matching products for store '{store_id}', skipping")
                continue
            created = await load_products(session, tenant.id, store_products)
            print(f"  {tenant.name}: {created} created ({len(store_products)} in sample)")


if __name__ == "__main__":
    asyncio.run(main())
