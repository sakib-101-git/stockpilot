"""Bulk-loads products into a tenant from a DataFrame of sku/category.

Used by scripts/synth/load_products.py to seed the M5 product catalog.
Idempotent: skips any sku that already exists for the tenant.

Product names are not present in M5, so `name` is set equal to `sku` — this
is a known simplification, not real data.
"""

import uuid

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product


async def load_products(session: AsyncSession, tenant_id: uuid.UUID, products: pd.DataFrame) -> int:
    """Create a Product row for each sku in `products` not already present.

    `products` must have columns: sku, cat_id. Returns the number created.
    """
    await session.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )

    existing = await session.execute(select(Product.sku).where(Product.tenant_id == tenant_id))
    existing_skus = set(existing.scalars().all())

    to_create = products[~products["sku"].isin(existing_skus)]
    for row in to_create.itertuples():
        session.add(Product(tenant_id=tenant_id, sku=row.sku, name=row.sku, category=row.cat_id))

    await session.commit()
    return len(to_create)
