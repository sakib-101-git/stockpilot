import numpy as np
import pandas as pd
import pytest

from ml.backtest import split_fold
from ml.features import calendar_features, training_table
from ml.lgbm import backtest, fit, forecast, loss_weights

N_DAYS = 200
SMALL = {"n_estimators": 5, "min_child_samples": 5, "num_leaves": 7}


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


def make_model(cutoff: int = 170, weighted: bool = False):
    values, prices, cal, states = make_inputs()
    table = training_table(
        values, prices, cal, states, cutoff=cutoff, horizon=14, stride=7, first_origin=20
    )
    return values, prices, cal, states, fit(table, weighted=weighted, params=SMALL)


def test_smaller_scale_gets_a_larger_weight() -> None:
    weights = loss_weights(pd.Series([1.0, 2.0, 4.0]))
    assert weights[0] > weights[1] > weights[2]


def test_undefined_scale_gets_the_median_weight() -> None:
    weights = loss_weights(pd.Series([1.0, 2.0, 4.0, np.nan]))
    assert weights[3] == pytest.approx(0.5)


def test_extreme_weights_are_capped_at_the_99th_percentile() -> None:
    scale = pd.Series(np.r_[np.full(99, 1.0), 1e-6])
    weights = loss_weights(scale)
    assert weights.max() < 1e6
    assert weights.max() == pytest.approx(np.quantile(1 / scale.to_numpy(), 0.99))


def test_all_undefined_scales_fall_back_to_equal_weights() -> None:
    assert loss_weights(pd.Series([np.nan, np.nan])).tolist() == [1.0, 1.0]


def test_forecast_has_the_shape_of_the_actuals_and_is_not_negative() -> None:
    values, prices, cal, states, model = make_model(weighted=True)
    predicted = forecast(model, values, prices, cal, states, origin=170, horizon=14)
    _, actual = split_fold(values, 170, horizon=14)
    assert predicted.shape == actual.shape
    assert (predicted >= 0).all()


def test_forecast_ignores_actual_sales_after_the_origin() -> None:
    values, prices, cal, states, model = make_model()
    before = forecast(model, values, prices, cal, states, origin=170, horizon=14)

    changed = values.copy()
    changed[:, 170:] = 1e9
    after = forecast(model, changed, prices, cal, states, origin=170, horizon=14)

    np.testing.assert_array_equal(before, after)


def test_backtest_returns_one_row_per_origin_with_all_metrics() -> None:
    values, prices, cal, states = make_inputs()
    results = backtest(
        values, prices, cal, states, origins=(150, 170), horizon=14, params=SMALL, name="lgbm"
    )
    assert list(results["origin"]) == [150, 170]
    assert set(results["method"]) == {"lgbm"}
    assert {"MAE", "RMSE", "bias", "MASE", "RMSSE"} <= set(results.columns)
