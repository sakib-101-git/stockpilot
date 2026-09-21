import numpy as np
import pytest

from ml.quantiles import interval_breakdown, speed_groups


def test_speed_groups_split_series_into_equal_thirds() -> None:
    history = np.tile(np.arange(1.0, 7.0)[:, None], (1, 60))
    assert list(speed_groups(history)) == ["slow", "slow", "medium", "medium", "fast", "fast"]


def test_breakdown_reports_each_group_separately() -> None:
    lower = np.array([[0.0, 0.0], [1.0, 1.0]])
    upper = np.array([[2.0, 2.0], [3.0, 3.0]])
    actual = np.array([[0.0, 2.0], [2.0, 0.0]])
    out = interval_breakdown(lower, upper, actual, np.array(["a", "b"])).set_index("group")

    assert out.loc["a", "coverage"] == 1.0
    assert out.loc["b", "coverage"] == 0.5
    assert out.loc["b", "below_lower"] == 0.5
    assert out.loc["b", "above_upper"] == 0.0
    assert out.loc["a", "lower_is_zero"] == 1.0
    assert out.loc["b", "lower_is_zero"] == 0.0
    assert out.loc["a", "width"] == 2.0


def test_coverage_and_the_two_miss_rates_add_up_to_one() -> None:
    rng = np.random.default_rng(1)
    lower = rng.uniform(0, 2, size=(5, 10))
    upper = lower + rng.uniform(0, 2, size=(5, 10))
    actual = rng.uniform(0, 4, size=(5, 10))
    row = interval_breakdown(lower, upper, actual, np.full(5, "all")).iloc[0]
    assert row["coverage"] + row["below_lower"] + row["above_upper"] == pytest.approx(1.0)
