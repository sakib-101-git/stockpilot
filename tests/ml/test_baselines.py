import numpy as np
import pytest

from ml.baselines import BASELINES, moving_average, naive, seasonal_naive, zero


def test_zero_forecast_is_all_zeros() -> None:
    forecast = zero(np.ones((2, 5)), 3)
    assert forecast.shape == (2, 3)
    assert (forecast == 0).all()


def test_naive_repeats_the_last_value() -> None:
    history = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    assert naive(history, 2).tolist() == [[3.0, 3.0], [6.0, 6.0]]


def test_seasonal_naive_repeats_the_last_week() -> None:
    history = np.arange(1.0, 15.0).reshape(1, 14)
    expected = [[8, 9, 10, 11, 12, 13, 14, 8, 9, 10]]
    assert seasonal_naive(history, 10).tolist() == expected


def test_moving_average_ignores_days_before_launch() -> None:
    history = np.array([[np.nan, np.nan, 2.0, 4.0]])
    assert moving_average(history, 2).tolist() == [[3.0, 3.0]]


@pytest.mark.parametrize("name", list(BASELINES))
def test_every_baseline_returns_one_row_per_series_and_one_column_per_day(name: str) -> None:
    history = np.arange(1.0, 61.0).reshape(2, 30)
    assert BASELINES[name](history, 28).shape == (2, 28)
