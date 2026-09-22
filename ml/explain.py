"""Per-forecast feature explanations using SHAP.

Computed on demand against the champion model, not pre-stored — SHAP on a
single row is fast, and storing per-row explanations for every forecast
would multiply the forecasts table's size for data rarely looked at.
"""

import numpy as np
import pandas as pd
import shap

from ml.features import FEATURE_COLUMNS


def explain_row(model, feature_row: pd.Series) -> list[dict]:
    """SHAP values for one feature row, sorted by absolute impact, descending.

    `feature_row` must have exactly FEATURE_COLUMNS' columns, in a single-row
    DataFrame-compatible Series (e.g. one row from build_forecast_rows).
    """
    explainer = shap.TreeExplainer(model)
    row_df = feature_row[FEATURE_COLUMNS].to_frame().T
    shap_values = explainer.shap_values(row_df)

    values = np.asarray(shap_values).reshape(-1)
    contributions = [
        {"feature": col, "value": float(feature_row[col]), "impact": float(val)}
        for col, val in zip(FEATURE_COLUMNS, values, strict=True)
    ]
    contributions.sort(key=lambda c: abs(c["impact"]), reverse=True)
    return contributions


async def explain_forecast(session, tenant_id, product_id, target_date, calendar_path):
    """Rebuild the feature row for one (product, target_date) forecast and explain it.

    Loads the current champion model and tenant history fresh — this is a
    read-only, on-demand operation, not something the nightly task needs.
    """
    from app.db.models import Product, Tenant
    from app.services.forecast_data import load_tenant_history
    from ml.features import build_forecast_rows
    from ml.registry import load_champion
    from workers.tasks_forecast import align_calendar

    product = await session.get(Product, product_id)
    if product is None or product.tenant_id != tenant_id:
        raise ValueError("product not found for this tenant")

    tenant = await session.get(Tenant, tenant_id)
    history = await load_tenant_history(session, tenant_id)
    if product_id not in history.product_ids:
        raise ValueError("no history available for this product")

    origin = history.n_days
    target_day_number = (target_date - history.first_day).days + 1
    horizon_h = target_day_number - origin
    if horizon_h < 1:
        raise ValueError("target_date is not in the future relative to the tenant's history")

    cal = align_calendar(calendar_path, history.first_day, origin + horizon_h)
    states = [tenant.state or "CA"] * len(history.product_ids)

    rows = build_forecast_rows(
        history.values, history.prices, cal, states, origin=origin, horizon=horizon_h
    )
    product_row_idx = history.product_ids.index(product_id)
    row = rows[(rows["series_idx"] == product_row_idx) & (rows["h"] == horizon_h)]
    if row.empty:
        raise ValueError("could not rebuild the feature row (insufficient history)")

    model = load_champion()
    return explain_row(model, row.iloc[0])
