import numpy as np
import pandas as pd
import pytest

from ml.backtest import make_grid, run_backtest, split_fold
from ml.baselines import BASELINES


def make_values(n_series: int = 3, n_days: int = 120) -> np.ndarray:
    return np.tile(np.arange(1, n_days + 1, dtype=float), (n_series, 1))


def test_make_grid_puts_series_in_rows_and_days_in_columns() -> None:
    long = pd.DataFrame(
        {
            "store_id": ["S1", "S1", "S1", "S2", "S2"],
            "item_id": ["A", "A", "A", "B", "B"],
            "d": ["d_1", "d_2", "d_3", "d_2", "d_3"],
            "units": [1, 2, 3, 5, 6],
        }
    )
    grid = make_grid(long, n_days=3)
    assert grid.shape == (2, 3)
    assert grid.loc["S1/A"].tolist() == [1, 2, 3]
    assert np.isnan(grid.loc["S2/B", 1])
    assert grid.loc["S2/B", 3] == 6


def test_history_stops_at_the_origin_and_actuals_start_right_after() -> None:
    history, actual = split_fold(make_values(), origin=100, horizon=10)
    assert history.shape == (3, 100)
    assert history.max() == 100.0
    assert actual.shape == (3, 10)
    assert actual.min() == 101.0
    assert actual.max() == 110.0


def test_forecaster_never_sees_the_future() -> None:
    values = make_values()
    values[:, 100:] = 1e9
    grid = pd.DataFrame(values, columns=range(1, 121))
    seen = []

    def spy(history: np.ndarray, horizon: int) -> np.ndarray:
        seen.append(history.max())
        return np.zeros((history.shape[0], horizon))

    run_backtest(grid, {"spy": spy}, folds=(100,), horizon=10)
    assert seen == [100.0]


def test_series_with_too_little_history_are_dropped() -> None:
    values = make_values(n_series=2)
    values[0, :59] = np.nan
    values[1, :39] = np.nan
    history, _ = split_fold(values, origin=100, horizon=10, min_history=56)
    assert history.shape[0] == 1
    assert np.isnan(history[0, 38])
    assert history[0, 39] == 40.0


def test_series_launched_after_the_origin_are_dropped() -> None:
    values = make_values(n_series=2)
    values[0, :105] = np.nan
    history, _ = split_fold(values, origin=100, horizon=10, min_history=56)
    assert history.shape[0] == 1


def test_history_is_read_only() -> None:
    history, _ = split_fold(make_values(), origin=100, horizon=10)
    with pytest.raises(ValueError):
        history[0, 0] = 5.0


def test_fold_beyond_the_data_is_rejected() -> None:
    with pytest.raises(ValueError):
        split_fold(make_values(), origin=115, horizon=10)


def test_run_backtest_returns_one_row_per_fold_and_method() -> None:
    grid = pd.DataFrame(make_values(), columns=range(1, 121))
    results = run_backtest(grid, BASELINES, folds=(90, 100), horizon=10)
    assert len(results) == 2 * len(BASELINES)
    assert set(results["origin"]) == {90, 100}
    assert {"MAE", "RMSE", "bias", "MASE", "RMSSE"} <= set(results.columns)


def test_wrong_forecast_shape_is_rejected() -> None:
    grid = pd.DataFrame(make_values(), columns=range(1, 121))

    def bad(history: np.ndarray, horizon: int) -> np.ndarray:
        return np.zeros((1, 1))

    with pytest.raises(ValueError, match="shape"):
        run_backtest(grid, {"bad": bad}, folds=(100,), horizon=10)
