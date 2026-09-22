"""Nightly forecast generation: trains on real stock_movements history,
registers the model via MLflow, and writes Forecast rows for the next
28 days per product.

Price and zero-sale-day simplifications: see app/services/forecast_data.py.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Forecast, Tenant
from app.services.forecast_data import load_tenant_history
from ml.features import calendar_features, training_table
from ml.lgbm import fit
from ml.lgbm import forecast as lgbm_forecast
from ml.quantiles import fit_quantile
from ml.registry import champion_version, log_and_register, promote_to_champion

HORIZON = 28
MIN_HISTORY = 56


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


def eligible_product_ids(
    values: np.ndarray, product_ids: list[uuid.UUID], origin: int, min_history: int
) -> list[uuid.UUID]:
    """Product ids with at least min_history observed days by origin, in the
    same row order forecast() uses internally, so results line up correctly.
    """
    observed = ~np.isnan(values[:, :origin])
    first_day = np.where(observed.any(axis=1), observed.argmax(axis=1) + 1, np.inf)
    keep = np.flatnonzero(first_day <= origin - min_history)
    return [product_ids[i] for i in keep]


async def generate_forecasts_for_tenant(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    calendar_path,
    horizon: int = HORIZON,
    min_history: int = MIN_HISTORY,
) -> int:
    """Train, register, and forecast for one tenant. Returns the number of
    Forecast rows written. Raises ValueError if there is not enough history.
    """
    await _set_tenant(session, tenant_id)

    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise ValueError(f"tenant {tenant_id} not found")

    history = await load_tenant_history(session, tenant_id)
    if history.n_days < min_history + horizon:
        raise ValueError(
            f"tenant {tenant_id} has {history.n_days} days of history, "
            f"need at least {min_history + horizon}"
        )

    cal = align_calendar(calendar_path, history.first_day, history.n_days)
    states = [tenant.state or "CA"] * len(history.product_ids)

    origin = history.n_days
    table = training_table(
        history.values, history.prices, cal, states, cutoff=origin, horizon=horizon
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

    point = lgbm_forecast(
        model, history.values, history.prices, cal, states, origin, horizon, min_history
    )
    upper_model = fit_quantile(table, q=0.9, weighted=False)
    upper = lgbm_forecast(
        upper_model,
        history.values,
        history.prices,
        cal,
        states,
        origin,
        horizon,
        min_history,
    )

    eligible_ids = eligible_product_ids(history.values, history.product_ids, origin, min_history)
    if point.shape[0] != len(eligible_ids):
        raise ValueError(
            f"forecast produced {point.shape[0]} rows but {len(eligible_ids)} products "
            "are eligible; row alignment cannot be trusted"
        )

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
