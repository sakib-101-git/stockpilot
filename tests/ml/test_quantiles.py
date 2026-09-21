import numpy as np
import pytest

from ml.quantiles import empirical_quantile


def test_quantiles_of_a_simple_history() -> None:
    history = np.array([[1.0, 2.0, 3.0, 4.0, 5.0]])
    assert empirical_quantile(history, 2, 0.0, window=5).tolist() == [[1.0, 1.0]]
    assert empirical_quantile(history, 2, 0.5, window=5).tolist() == [[3.0, 3.0]]
    assert empirical_quantile(history, 2, 1.0, window=5).tolist() == [[5.0, 5.0]]


def test_only_the_last_window_days_count() -> None:
    history = np.array([[100.0, 1.0, 2.0, 3.0]])
    assert empirical_quantile(history, 1, 1.0, window=3)[0, 0] == 3.0


def test_days_before_launch_are_ignored() -> None:
    history = np.array([[np.nan, np.nan, 2.0, 4.0]])
    assert empirical_quantile(history, 1, 0.5, window=4)[0, 0] == pytest.approx(3.0)


def test_output_has_one_row_per_series_and_one_column_per_day() -> None:
    assert empirical_quantile(np.ones((3, 60)), 28, 0.9).shape == (3, 28)
