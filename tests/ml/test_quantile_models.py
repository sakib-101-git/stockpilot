import numpy as np
import pandas as pd

from ml.features import calendar_features, training_table
from ml.quantiles import (
    empirical_backtest,
    fit_quantile,
    quantile_backtest,
    quantile_forecasts,
)

N_DAYS = 200
SMALL = {"n_estimators": 5, "min_child_samples": 5, "num_leaves": 7}
METRIC_COLUMNS = {"coverage", "width", "pinball_10", "pinball_90", "zero_upper", "crossed"}


def make_inputs():
    rng = np.random.default_rng(0)
    values = rng.poisson(2.0, size=(4, N_DAYS)).astype(float)
    values[1, :30] = np.nan
    prices = np.full((4, N_DAYS), 2.0)
    prices[1, :30] = np.nan

    event = [None] * N_DAYS
    event[49] = "Cultural"
    cal = pd.DataFrame(
        {
            "d": [f"d_{i}" for i in range(1, N_DAYS + 1)],
            "date": pd.date_range("2011-01-29", periods=N_DAYS),
            "event_type_1": event,
            "snap_CA": [0] * N_DAYS,
            "snap_TX": [0] * N_DAYS,
            "snap_WI": [0] * N_DAYS,
        }
    )
    return values, prices, calendar_features(cal), ["CA", "CA", "TX", "WI"]


def make_pair(cutoff: int = 170):
    values, prices, cal, states = make_inputs()
    table = training_table(
        values, prices, cal, states, cutoff=cutoff, horizon=14, stride=7, first_origin=20
    )
    models = [fit_quantile(table, q, params=SMALL) for q in (0.1, 0.9)]
    return values, prices, cal, states, table, models


def test_the_high_quantile_model_predicts_higher_than_the_low_one() -> None:
    _, _, _, _, table, (low, high) = make_pair()
    features = table[list(low.feature_name_)]
    assert high.predict(features).mean() > low.predict(features).mean()


def test_forecasts_are_ordered_non_negative_and_the_right_shape() -> None:
    values, prices, cal, states, _, models = make_pair()
    grids, crossed = quantile_forecasts(models, values, prices, cal, states, 170, horizon=14)
    assert grids.shape == (2, 4, 14)
    assert (grids[0] <= grids[1]).all()
    assert (grids >= 0).all()
    assert 0.0 <= crossed <= 1.0


def test_forecasts_ignore_actual_sales_after_the_origin() -> None:
    values, prices, cal, states, _, models = make_pair()
    before, _ = quantile_forecasts(models, values, prices, cal, states, 170, horizon=14)

    changed = values.copy()
    changed[:, 170:] = 1e9
    after, _ = quantile_forecasts(models, changed, prices, cal, states, 170, horizon=14)

    np.testing.assert_array_equal(before, after)


def test_quantile_backtest_returns_one_scored_row_per_origin() -> None:
    values, prices, cal, states = make_inputs()
    results = quantile_backtest(
        values, prices, cal, states, origins=(150, 170), horizon=14, params=SMALL, name="q"
    )
    assert list(results["origin"]) == [150, 170]
    assert set(results["method"]) == {"q"}
    assert METRIC_COLUMNS <= set(results.columns)
    assert results["coverage"].between(0, 1).all()
    assert (results["width"] >= 0).all()


def test_empirical_backtest_on_a_constant_series_is_perfect() -> None:
    results = empirical_backtest(np.full((2, 200), 3.0), origins=(150,), window=28)
    row = results.iloc[0]
    assert row["coverage"] == 1.0
    assert row["width"] == 0.0
    assert row["pinball_10"] == 0.0
    assert row["pinball_90"] == 0.0
