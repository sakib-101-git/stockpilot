"""Feature drift detection using Evidently.

Compares a tenant's engineered demand features now against the same
features at an earlier point in their history, using the exact
origin_features function real training already uses. This is a
deliberate simplification: Forecast rows do not record which origin day
a given model version actually trained on, so this does not reconstruct
the champion model's literal training set — it answers a closely related
question (has this tenant's demand behavior shifted meaningfully over
the reference window) without adding new tracking this week.
"""

import uuid
from dataclasses import dataclass

import pandas as pd
from evidently import Report
from evidently.presets import DataDriftPreset
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.forecast_data import load_tenant_history
from ml.features import origin_features

DEFAULT_REFERENCE_DAYS_AGO = 90
DRIFT_SHARE_THRESHOLD = 0.3


@dataclass
class DriftResult:
    reference_origin: int
    current_origin: int
    drift_share: float
    drifted_columns: list[str]
    is_significant: bool


def build_feature_snapshot(values, origin: int) -> pd.DataFrame:
    return origin_features(values, origin)


async def check_drift(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    reference_days_ago: int = DEFAULT_REFERENCE_DAYS_AGO,
) -> DriftResult:
    """Raises ValueError if there isn't enough history to compare two
    points reference_days_ago apart.
    """
    history = await load_tenant_history(session, tenant_id)
    current_origin = history.n_days
    reference_origin = current_origin - reference_days_ago

    if reference_origin < 1:
        raise ValueError(
            f"not enough history ({history.n_days} days) to compare against "
            f"a reference point {reference_days_ago} days ago"
        )

    # Excluded from drift comparison: history_days and days_since_sale are
    # anchored to the origin day itself, so they shift mechanically by the
    # gap between reference and current origins regardless of any real
    # change in demand behavior — including them would make drift_share
    # near 1.0 on every single call, for every tenant, always. Confirmed
    # by a real first run: with them included, all 8 features "drifted"
    # even on ordinary CA_1 data with no known behavior change.
    DRIFT_FEATURE_COLUMNS = [
        "last_day",
        "mean_7",
        "mean_28",
        "mean_56",
        "zero_share_28",
        "scale_sq",
    ]

    reference_snapshot = build_feature_snapshot(history.values, reference_origin)
    current_snapshot = build_feature_snapshot(history.values, current_origin)

    reference_snapshot = reference_snapshot[DRIFT_FEATURE_COLUMNS].dropna()
    current_snapshot = current_snapshot[DRIFT_FEATURE_COLUMNS].dropna()

    report = Report([DataDriftPreset()], include_tests=True)
    result = report.run(current_data=current_snapshot, reference_data=reference_snapshot)

    import json

    parsed = json.loads(result.json())
    drift_share = 0.0
    drifted_columns: list[str] = []
    for metric in parsed["metrics"]:
        if metric["metric_name"].startswith("DriftedColumnsCount"):
            drift_share = metric["value"]["share"]
        elif metric["metric_name"].startswith("ValueDrift(column="):
            column = metric["metric_name"].split("column=")[1].split(",")[0]
            p_value = metric["value"]
            if p_value < 0.05:
                drifted_columns.append(column)

    return DriftResult(
        reference_origin=reference_origin,
        current_origin=current_origin,
        drift_share=drift_share,
        drifted_columns=drifted_columns,
        is_significant=drift_share > DRIFT_SHARE_THRESHOLD,
    )
