import math

import numpy as np
import pytest

from ml.metrics import bias, coverage, mae, mase, mean_width, one_step_scale, pinball, rmse, rmsse

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


def test_pinball_charges_misses_asymmetrically() -> None:
    actual, forecast = np.array([10.0, 2.0]), np.array([6.0, 6.0])
    assert pinball(forecast[:1], actual[:1], 0.9) == pytest.approx(3.6)
    assert pinball(forecast[1:], actual[1:], 0.9) == pytest.approx(0.4)
    assert pinball(forecast, actual, 0.9) == pytest.approx(2.0)


def test_median_pinball_is_half_the_mae() -> None:
    forecast, actual = np.array([1.0, 2.0, 3.0]), np.array([2.0, 2.0, 5.0])
    assert pinball(forecast, actual, 0.5) == pytest.approx(mae(forecast, actual) / 2)


def test_perfect_quantile_forecast_scores_zero() -> None:
    actual = np.array([1.0, 4.0])
    assert pinball(actual, actual, 0.1) == 0.0


def test_coverage_counts_values_inside_the_interval_ends_included() -> None:
    lower, upper = np.zeros(4), np.full(4, 2.0)
    actual = np.array([1.0, 2.0, 3.0, 0.0])
    assert coverage(lower, upper, actual) == pytest.approx(0.75)


def test_mean_width() -> None:
    assert mean_width(np.array([0.0, 1.0]), np.array([2.0, 5.0])) == pytest.approx(3.0)
