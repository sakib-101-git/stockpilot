import numpy as np
import pandas as pd
import pytest

from ml.features import origin_features


def test_series_that_launched_after_day_one() -> None:
    row = origin_features(np.array([[np.nan, 2.0, 0.0, 4.0]]), origin=4).iloc[0]
    assert row["last_day"] == 4.0
    assert row["mean_7"] == pytest.approx(2.0)
    assert row["mean_56"] == pytest.approx(2.0)
    assert row["zero_share_28"] == pytest.approx(1 / 3)
    assert row["days_since_sale"] == 0
    assert row["history_days"] == 3


def test_a_single_sale_amid_zeros() -> None:
    row = origin_features(np.array([[0.0, 0.0, 0.0, 5.0, 0.0, 0.0]]), origin=6).iloc[0]
    assert row["last_day"] == 0.0
    assert row["mean_7"] == pytest.approx(5 / 6)
    assert row["zero_share_28"] == pytest.approx(5 / 6)
    assert row["days_since_sale"] == 2
    assert row["history_days"] == 6


def test_series_that_never_sold() -> None:
    row = origin_features(np.array([[0.0, 0.0, 0.0]]), origin=3).iloc[0]
    assert row["days_since_sale"] == 3


def test_days_after_the_origin_are_ignored() -> None:
    row = origin_features(np.array([[1.0, 2.0, 3.0, 4.0, 5.0]]), origin=3).iloc[0]
    assert row["last_day"] == 3.0
    assert row["mean_7"] == pytest.approx(2.0)


def test_series_that_has_not_launched_gets_missing_values() -> None:
    row = origin_features(np.full((1, 4), np.nan), origin=4).iloc[0]
    assert np.isnan(row["mean_7"])
    assert np.isnan(row["history_days"])
    assert row["days_since_sale"] == 4


def test_features_do_not_change_when_the_future_changes() -> None:
    rng = np.random.default_rng(0)
    values = rng.poisson(1.0, size=(5, 100)).astype(float)
    values[0, :30] = np.nan

    before = origin_features(values, origin=60)
    values[:, 60:] = 1e9
    after = origin_features(values, origin=60)

    pd.testing.assert_frame_equal(before, after)


@pytest.mark.parametrize("origin", [0, 11])
def test_origin_outside_the_data_is_rejected(origin: int) -> None:
    with pytest.raises(ValueError):
        origin_features(np.ones((1, 10)), origin)


def test_scale_sq_is_the_mean_squared_one_step_change() -> None:
    row = origin_features(np.array([[np.nan, 2.0, 0.0, 4.0]]), origin=4).iloc[0]
    assert row["scale_sq"] == pytest.approx(10.0)


def test_scale_sq_is_missing_for_constant_or_unlaunched_series() -> None:
    constant = origin_features(np.zeros((1, 5)), origin=5).iloc[0]
    unlaunched = origin_features(np.full((1, 5), np.nan), origin=5).iloc[0]
    assert np.isnan(constant["scale_sq"])
    assert np.isnan(unlaunched["scale_sq"])
