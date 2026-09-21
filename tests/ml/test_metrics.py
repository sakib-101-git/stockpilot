import math

import numpy as np
import pytest

from ml.metrics import bias, mae, mase, one_step_scale, rmse, rmsse

FORECAST = np.array([[1.0, 2.0, 3.0]])
ACTUAL = np.array([[2.0, 2.0, 5.0]])
HISTORY = np.array([[0.0, 2.0, 2.0, 5.0]])


def test_mae_rmse_and_bias() -> None:
    assert mae(FORECAST, ACTUAL) == pytest.approx(1.0)
    assert rmse(FORECAST, ACTUAL) == pytest.approx(math.sqrt(5 / 3))
    assert bias(FORECAST, ACTUAL) == pytest.approx(-1.0)


def test_scale_is_the_average_one_step_change() -> None:
    assert one_step_scale(HISTORY)[0] == pytest.approx(5 / 3)
    assert one_step_scale(HISTORY, squared=True)[0] == pytest.approx(13 / 3)


def test_scale_ignores_days_before_launch() -> None:
    history = np.array([[np.nan, np.nan, 1.0, 3.0, 2.0]])
    assert one_step_scale(history)[0] == pytest.approx(1.5)


def test_constant_history_has_no_scale() -> None:
    assert np.isnan(one_step_scale(np.array([[0.0, 0.0, 0.0, 0.0]]))[0])


def test_mase_and_rmsse_on_a_hand_worked_example() -> None:
    forecast, actual = np.array([[3.0]]), np.array([[5.0]])
    assert mase(forecast, actual, HISTORY) == pytest.approx(1.2)
    assert rmsse(forecast, actual, HISTORY) == pytest.approx(math.sqrt(12 / 13))


def test_perfect_forecast_scores_zero() -> None:
    actual = np.array([[1.0, 4.0]])
    assert mase(actual, actual, HISTORY) == 0.0
    assert rmsse(actual, actual, HISTORY) == 0.0


def test_series_without_a_scale_are_skipped_not_counted_as_zero() -> None:
    history = np.array([[0.0, 0.0, 0.0, 0.0], [0.0, 2.0, 2.0, 5.0]])
    forecast = np.array([[9.0], [3.0]])
    actual = np.array([[1.0], [5.0]])
    assert mase(forecast, actual, history) == pytest.approx(1.2)
