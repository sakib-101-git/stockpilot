"""Reorder point and order quantity, built directly on the Week 7 upper-bound
forecast rather than a re-derived normal-distribution safety-stock formula.

reorder_point = sum of the upper-bound forecast over a lead-time window sized
as lead_time_mean + lead_time_std (one std of buffer on delivery timing,
since lead time itself is uncertain, not just demand).
"""

import math
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Forecast, ProductSupplier, StockMovement

MAX_FORECAST_HORIZON = 28


@dataclass
class ReorderRecommendation:
    product_id: uuid.UUID
    current_stock: int
    reorder_point: float
    lead_time_window_days: int
    should_reorder: bool
    order_quantity: int


async def current_stock(session: AsyncSession, product_id: uuid.UUID) -> int:
    result = await session.execute(
        select(StockMovement.quantity).where(StockMovement.product_id == product_id)
    )
    return sum(row[0] for row in result.all())


async def get_reorder_recommendation(
    session: AsyncSession, product_id: uuid.UUID
) -> ReorderRecommendation:
    """Raises ValueError if there's no supplier link, no forecast, or the
    supplier's lead time exceeds the forecast horizon.
    """
    supplier_link = (
        await session.execute(
            select(ProductSupplier).where(ProductSupplier.product_id == product_id)
        )
    ).scalar_one_or_none()
    if supplier_link is None:
        raise ValueError(f"no supplier link for product {product_id}")

    lead_time_window = max(
        1,
        math.ceil(
            float(supplier_link.lead_time_days_mean) + float(supplier_link.lead_time_days_std)
        ),
    )
    if lead_time_window > MAX_FORECAST_HORIZON:
        raise ValueError(
            f"lead time window ({lead_time_window} days) exceeds the "
            f"forecast horizon ({MAX_FORECAST_HORIZON} days)"
        )

    latest_run = (
        await session.execute(
            select(Forecast.generated_at)
            .where(Forecast.product_id == product_id)
            .order_by(Forecast.generated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest_run is None:
        raise ValueError(f"no forecast for product {product_id}")

    forecast_rows = (
        (
            await session.execute(
                select(Forecast.upper_bound)
                .where(Forecast.product_id == product_id, Forecast.generated_at == latest_run)
                .order_by(Forecast.target_date)
                .limit(lead_time_window)
            )
        )
        .scalars()
        .all()
    )

    reorder_point = float(sum(forecast_rows))
    stock = await current_stock(session, product_id)

    should_reorder = stock < reorder_point
    raw_needed = max(0.0, reorder_point - stock)

    pack_size = supplier_link.pack_size
    moq = supplier_link.moq
    packs_needed = math.ceil(raw_needed / pack_size) if raw_needed > 0 else 0
    order_quantity = max(packs_needed * pack_size, moq) if should_reorder else 0

    return ReorderRecommendation(
        product_id=product_id,
        current_stock=stock,
        reorder_point=round(reorder_point, 2),
        lead_time_window_days=lead_time_window,
        should_reorder=should_reorder,
        order_quantity=order_quantity,
    )
