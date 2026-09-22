import numpy as np
import pandas as pd
import pytest

from ml.explain import explain_row
from ml.features import FEATURE_COLUMNS


def _make_tiny_model():
    import lightgbm as lgb

    rng = np.random.default_rng(0)
    n = 200
    x = pd.DataFrame({col: rng.random(n) for col in FEATURE_COLUMNS})
    for col in ("dow", "month", "event", "snap"):
        x[col] = rng.integers(0, 3, n).astype(float)
    y = x["mean_28"] * 5 + x["mean_7"] * 2 + rng.random(n)
    model = lgb.LGBMRegressor(n_estimators=10, verbose=-1)
    model.fit(x[FEATURE_COLUMNS], y)
    return model, x


def test_explain_row_returns_one_entry_per_feature() -> None:
    model, x = _make_tiny_model()
    result = explain_row(model, x.iloc[0])
    assert len(result) == len(FEATURE_COLUMNS)
    assert {r["feature"] for r in result} == set(FEATURE_COLUMNS)


def test_explain_row_is_sorted_by_absolute_impact_descending() -> None:
    model, x = _make_tiny_model()
    result = explain_row(model, x.iloc[0])
    impacts = [abs(r["impact"]) for r in result]
    assert impacts == sorted(impacts, reverse=True)


def test_explain_row_values_match_the_input_row() -> None:
    model, x = _make_tiny_model()
    row = x.iloc[0]
    result = explain_row(model, row)
    by_feature = {r["feature"]: r["value"] for r in result}
    for col in FEATURE_COLUMNS:
        assert by_feature[col] == pytest.approx(row[col])


def test_explain_row_impacts_sum_to_the_predictions_deviation_from_baseline() -> None:
    """Core SHAP correctness property: contributions + base value = prediction."""
    import shap

    model, x = _make_tiny_model()
    row = x.iloc[0]
    result = explain_row(model, row)

    explainer = shap.TreeExplainer(model)
    base_value = explainer.expected_value
    if hasattr(base_value, "__len__"):
        base_value = base_value[0]

    predicted = model.predict(row[FEATURE_COLUMNS].to_frame().T)[0]
    total_impact = sum(r["impact"] for r in result)
    assert base_value + total_impact == pytest.approx(predicted, abs=1e-4)


def test_mean_28_is_influential_when_the_target_scales_with_it() -> None:
    """The synthetic target is built mostly from mean_28; SHAP should notice."""
    model, x = _make_tiny_model()
    result = explain_row(model, x.iloc[0])
    top_feature = result[0]["feature"]
    assert top_feature == "mean_28"
