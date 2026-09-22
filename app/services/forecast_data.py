"""Loads a tenant's real sales history from stock_movements into the grid
shape ml.features / ml.lgbm expect (one row per product, one column per day).

Two documented simplifications versus the M5-backed backtest path:

1. Price: stock_movements has no price history, only Product.current_price
   (a single static value). Every day for a product uses that same price,
   so price_ratio (price / last known price) is always 1.0 here — an
   uninformative feature on this path, unlike the M5 path where real price
   history drives it.

2. Zero-sale days: stock_movements only has sale *events*, no explicit
   "zero sold today" rows. Days between a product's first and last known
   sale with no event are filled as 0 (assumed on-sale, no purchase) —
   days before the first sale stay NaN (assumed not yet launched), matching
   sales.parquet's convention. This is an assumption, not observed fact: a
   real stockout or delisting mid-range would be misread as a zero-sale day.

See docs/decisions for the write-up.
"""

import uuid
from dataclasses import dataclass
from datetime import date

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MovementType, Product, StockMovement


@dataclass
class TenantHistory:
    values: np.ndarray  # (n_products, n_days), NaN before a product's first sale
    prices: np.ndarray  # same shape, constant per product row
    product_ids: list[uuid.UUID]  # row order matches values/prices
    first_day: date  # calendar date that column 0 represents
    n_days: int


async def load_tenant_history(session: AsyncSession, tenant_id: uuid.UUID) -> TenantHistory:
    result = await session.execute(
        select(
            StockMovement.product_id,
            StockMovement.occurred_at,
            StockMovement.quantity,
            Product.current_price,
        )
        .join(Product, Product.id == StockMovement.product_id)
        .where(
            StockMovement.tenant_id == tenant_id,
            StockMovement.movement_type == MovementType.SALE,
        )
        .order_by(StockMovement.occurred_at)
    )
    rows = result.all()

    if not rows:
        return TenantHistory(
            values=np.empty((0, 0)),
            prices=np.empty((0, 0)),
            product_ids=[],
            first_day=date.today(),
            n_days=0,
        )

    dates = [r.occurred_at.date() for r in rows]
    first_day = min(dates)
    n_days = (max(dates) - first_day).days + 1

    product_ids = sorted({r.product_id for r in rows}, key=str)
    row_index = {pid: i for i, pid in enumerate(product_ids)}

    values = np.full((len(product_ids), n_days), np.nan)
    prices = np.full((len(product_ids), n_days), np.nan)
    first_sale_day = np.full(len(product_ids), n_days, dtype=int)
    last_sale_day = np.full(len(product_ids), -1, dtype=int)

    for r in rows:
        day = (r.occurred_at.date() - first_day).days
        product_row = row_index[r.product_id]
        units_sold = -r.quantity  # stored negative for a sale; model expects positive
        existing = values[product_row, day]
        values[product_row, day] = (0 if np.isnan(existing) else existing) + units_sold
        if r.current_price is not None:
            prices[product_row, day] = float(r.current_price)
        first_sale_day[product_row] = min(first_sale_day[product_row], day)
        last_sale_day[product_row] = max(last_sale_day[product_row], day)

    for i in range(len(product_ids)):
        # Interior gap-filling: between this product's first and last known
        # sale, a day with no event is assumed a zero-sale day, not "not
        # yet launched." Before the first sale, leave as NaN.
        start, end = first_sale_day[i], last_sale_day[i]
        interior = values[i, start : end + 1]
        interior[np.isnan(interior)] = 0.0

        known_prices = prices[i][~np.isnan(prices[i])]
        if len(known_prices):
            prices[i, start : end + 1] = known_prices[0]

    return TenantHistory(
        values=values,
        prices=prices,
        product_ids=product_ids,
        first_day=first_day,
        n_days=n_days,
    )
