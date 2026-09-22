"""Nightly forecast generation: trains on real stock_movements history,
registers the model via MLflow, and writes Forecast rows for the next
28 days per product.

Price and zero-sale-day simplifications: see app/services/forecast_data.py.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Forecast, Tenant
from app.services.forecast_data import load_tenant_history
from ml.features import calendar_features, training_table
from ml.lgbm import fit
from ml.lgbm import forecast_future as lgbm_forecast_future
from ml.quantiles import fit_quantile
from ml.registry import champion_version, log_and_register, promote_to_champion
from workers.celery_app import celery_app, run_async

HORIZON = 28
MIN_HISTORY = 56
DEFAULT_FIRST_ORIGIN = 100
DEFAULT_STRIDE = 7
DEFAULT_CALENDAR_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "processed" / "calendar.parquet"
)


async def _set_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


def align_calendar(calendar_path, first_day: date, n_days: int) -> pd.DataFrame:
    """Calendar features indexed 1..n_days, aligned to the tenant's actual first_day."""
    cal = pd.read_parquet(calendar_path)
    cal_features = calendar_features(cal)
    cal_dates = pd.to_datetime(cal["date"]).dt.date
    day_by_date = {d: i + 1 for i, d in enumerate(sorted(cal_dates.unique()))}

    if first_day not in day_by_date:
        raise ValueError(f"calendar has no entry for {first_day}; cannot align")

    offset = day_by_date[first_day] - 1
    aligned = cal_features.loc[cal_features.index.isin(range(offset + 1, offset + n_days + 1))]
    aligned = aligned.copy()
    aligned.index = aligned.index - offset
    return aligned


async def generate_forecasts_for_tenant(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    calendar_path,
    horizon: int = HORIZON,
    min_history: int = MIN_HISTORY,
    first_origin: int = DEFAULT_FIRST_ORIGIN,
    stride: int = DEFAULT_STRIDE,
) -> int:
    """Train, register, and forecast for one tenant. Returns the number of
    Forecast rows written. Raises ValueError if there is not enough history.
    """
    await _set_tenant(session, tenant_id)

    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise ValueError(f"tenant {tenant_id} not found")

    history = await load_tenant_history(session, tenant_id)
    required_days = max(min_history, first_origin) + horizon
    if history.n_days < required_days:
        raise ValueError(
            f"tenant {tenant_id} has {history.n_days} days of history, "
            f"need at least {required_days}"
        )

    cal_train = align_calendar(calendar_path, history.first_day, history.n_days)
    states = [tenant.state or "CA"] * len(history.product_ids)

    origin = history.n_days
    table = training_table(
        history.values,
        history.prices,
        cal_train,
        states,
        cutoff=origin,
        horizon=horizon,
        stride=stride,
        first_origin=first_origin,
    )

    model = fit(table, weighted=True)
    version = log_and_register(
        model,
        params={"tenant_id": str(tenant_id), "origin": origin, "weighted": True},
        metrics={},
        run_name=f"tenant-{tenant_id}-{datetime.now(UTC).isoformat()}",
    )
    promote_to_champion(version)
    model_version = champion_version()

    # Calendar for the forecast horizon must extend past the training data's
    # own range, up to origin + horizon, unlike cal_train above.
    cal_forecast = align_calendar(calendar_path, history.first_day, history.n_days + horizon)

    point, keep = lgbm_forecast_future(
        model, history.values, history.prices, cal_forecast, states, origin, horizon, min_history
    )

    upper_model = fit_quantile(table, q=0.9, weighted=False)
    upper, _ = lgbm_forecast_future(
        upper_model,
        history.values,
        history.prices,
        cal_forecast,
        states,
        origin,
        horizon,
        min_history,
    )

    eligible_ids = [history.product_ids[i] for i in keep]

    written = 0
    for row_i, product_id in enumerate(eligible_ids):
        for h in range(horizon):
            target_date = history.first_day + timedelta(days=origin + h)
            session.add(
                Forecast(
                    tenant_id=tenant_id,
                    product_id=product_id,
                    target_date=target_date,
                    point_estimate=round(float(max(0, point[row_i, h])), 2),
                    upper_bound=round(float(max(0, upper[row_i, h])), 2),
                    model_version=model_version,
                )
            )
            written += 1
    await session.commit()
    return written


async def _run_nightly_forecasts_async(calendar_path: Path) -> dict[str, int]:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import settings

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    results: dict[str, int] = {}
    try:
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as session:
            tenants = (await session.execute(select(Tenant))).scalars().all()

        for tenant in tenants:
            async with session_maker() as session:
                try:
                    written = await generate_forecasts_for_tenant(session, tenant.id, calendar_path)
                    results[str(tenant.id)] = written
                    print(f"tenant {tenant.name}: wrote {written} forecast rows")
                except Exception as exc:
                    results[str(tenant.id)] = -1
                    print(f"tenant {tenant.name}: FAILED - {exc}")
    finally:
        await engine.dispose()
    return results


@celery_app.task(name="workers.run_nightly_forecasts")
def run_nightly_forecasts() -> dict[str, int]:
    """Celery entry point. Generates forecasts for every tenant, nightly."""
    return run_async(_run_nightly_forecasts_async(DEFAULT_CALENDAR_PATH))
