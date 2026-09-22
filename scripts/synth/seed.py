"""Write synthetic suppliers, links, opening stock and batches into Postgres.

Run once per environment: `uv run python -m scripts.synth.seed`
Idempotent per tenant: re-running skips tenants that already have suppliers.
"""

import asyncio
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Batch,
    MovementType,
    Product,
    ProductSupplier,
    StockMovement,
    Supplier,
    Tenant,
)
from app.db.session import SessionLocal
from scripts.synth.generate import (
    SEED,
    plan_batches,
    plan_links,
    plan_opening_stock,
    plan_suppliers,
    summarize_products,
)

DATA_START = date(2011, 1, 29)
DEFAULT_ORIGIN_DAY = 1913


async def _seed_tenant(
    session: AsyncSession,
    tenant: Tenant,
    products: pd.DataFrame,
    origin_date: date,
    rng: np.random.Generator,
) -> None:
    # Row-level security requires app.current_tenant to be set before the
    # very first query on a tenant-scoped table, or that query silently
    # returns zero rows (see the CSV import fix earlier this week).
    await session.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
        {"tenant_id": str(tenant.id)},
    )

    existing = await session.execute(select(Supplier).where(Supplier.tenant_id == tenant.id))
    if existing.scalars().first() is not None:
        print(f"  {tenant.name}: already seeded, skipping")
        return

    db_products = (
        (await session.execute(select(Product).where(Product.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    product_by_sku = {p.sku: p for p in db_products}

    store_products = products[products["sku"].isin(product_by_sku)]
    if store_products.empty:
        print(f"  {tenant.name}: no matching products in DB, skipping")
        return

    supplier_plans = plan_suppliers(tenant.name, rng)
    suppliers = [
        Supplier(tenant_id=tenant.id, name=p.name, contact_email=p.contact_email)
        for p in supplier_plans
    ]
    session.add_all(suppliers)
    await session.flush()
    supplier_by_name = {s.name: s for s in suppliers}

    links = plan_links(store_products, supplier_plans, rng)
    session.add_all(
        ProductSupplier(
            tenant_id=tenant.id,
            product_id=product_by_sku[link.product_sku].id,
            supplier_id=supplier_by_name[link.supplier_name].id,
            unit_cost=link.unit_cost,
            lead_time_days_mean=link.lead_time_days_mean,
            lead_time_days_std=link.lead_time_days_std,
            moq=link.moq,
            pack_size=link.pack_size,
        )
        for link in links
    )

    stock_plans = plan_opening_stock(store_products, origin_date, rng)
    session.add_all(
        StockMovement(
            tenant_id=tenant.id,
            product_id=product_by_sku[s.product_sku].id,
            movement_type=MovementType.RECEIPT,
            quantity=s.quantity,
            reference="synthetic opening stock",
            occurred_at=datetime.combine(s.occurred_on, datetime.min.time(), tzinfo=UTC),
        )
        for s in stock_plans
    )

    batch_plans = plan_batches(store_products, stock_plans, rng)
    session.add_all(
        Batch(
            tenant_id=tenant.id,
            product_id=product_by_sku[b.product_sku].id,
            batch_code=f"SYN-{b.product_sku}-{b.received_on.isoformat()}",
            quantity_received=b.quantity,
            quantity_remaining=b.quantity,
            received_at=b.received_on,
            expires_at=b.expires_on,
        )
        for b in batch_plans
    )

    await session.commit()
    print(
        f"  {tenant.name}: {len(suppliers)} suppliers, {len(links)} links, "
        f"{len(stock_plans)} stock movements, {len(batch_plans)} batches"
    )


async def main() -> None:
    root = Path(__file__).resolve().parents[2]
    sales = pd.read_parquet(root / "data" / "processed" / "sales.parquet")
    products = summarize_products(sales)
    origin_date = DATA_START + timedelta(days=DEFAULT_ORIGIN_DAY - 1)

    async with SessionLocal() as session:
        tenants = (await session.execute(select(Tenant))).scalars().all()
        print(f"found {len(tenants)} tenants")
        for i, tenant in enumerate(tenants):
            rng = np.random.default_rng(SEED + i)
            store_id = tenant.name.split(" ")[0]
            store_products = products[products["store_id"] == store_id]
            await _seed_tenant(session, tenant, store_products, origin_date, rng)


if __name__ == "__main__":
    asyncio.run(main())
