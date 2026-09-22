import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import Forecast, Product, User
from app.db.session import get_session
from app.schemas.forecast import ForecastDay, ForecastSummaryRow

router = APIRouter(tags=["forecasts"])


@router.get("/products/{product_id}/forecast", response_model=list[ForecastDay])
async def get_product_forecast(
    product_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Forecast]:
    product = await session.get(Product, product_id)
    if product is None or product.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Product not found")

    latest_run = await session.execute(
        select(Forecast.generated_at)
        .where(Forecast.product_id == product_id)
        .order_by(Forecast.generated_at.desc())
        .limit(1)
    )
    latest = latest_run.scalar_one_or_none()
    if latest is None:
        return []

    result = await session.execute(
        select(Forecast)
        .where(Forecast.product_id == product_id, Forecast.generated_at == latest)
        .order_by(Forecast.target_date)
    )
    return list(result.scalars().all())


@router.get("/forecasts/summary", response_model=list[ForecastSummaryRow])
async def get_forecast_summary(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    latest_per_product = (
        select(Forecast.product_id, Forecast.generated_at.label("latest"))
        .distinct(Forecast.product_id)
        .order_by(Forecast.product_id, Forecast.generated_at.desc())
        .subquery()
    )

    result = await session.execute(
        select(
            Forecast.product_id,
            Product.sku,
            Forecast.target_date,
            Forecast.point_estimate,
            Forecast.upper_bound,
        )
        .join(Product, Product.id == Forecast.product_id)
        .join(
            latest_per_product,
            (Forecast.product_id == latest_per_product.c.product_id)
            & (Forecast.generated_at == latest_per_product.c.latest),
        )
        .where(Forecast.tenant_id == current_user.tenant_id)
        .order_by(Product.sku, Forecast.target_date)
    )
    rows = result.all()

    seen: set[uuid.UUID] = set()
    summary = []
    for row in rows:
        if row.product_id in seen:
            continue
        seen.add(row.product_id)
        summary.append(row)
    return summary
