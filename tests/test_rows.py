import numpy as np
import pandas as pd
import pytest

from ml.backtest import make_grid
from ml.features import (
    FEATURE_COLUMNS,
    build_rows,
    calendar_features,
    series_states,
    training_table,
)

N_DAYS = 120


def make_calendar(n_days: int = N_DAYS) -> pd.DataFrame:
    event = [None] * n_days
    snap_ca = [0] * n_days
    event[49] = "Cultural"
    snap_ca[49] = 1
    return pd.DataFrame(
        {
            "d": [f"d_{i}" for i in range(1, n_days + 1)],
            "date": pd.date_range("2011-01-29", periods=n_days),
            "event_type_1": event,
            "snap_CA": snap_ca,
            "snap_TX": [0] * n_days,
            "snap_WI": [0] * n_days,
        }
    )


def make_inputs():
    values = np.tile(np.arange(1.0, N_DAYS + 1), (2, 1))
    values[1, :40] = np.nan
    prices = np.full((2, N_DAYS), 2.0)
    prices[1, :40] = np.nan
    prices[0, 60:] = 3.0
    return values, prices, calendar_features(make_calendar()), ["CA", "TX"]


def test_make_grid_can_pivot_prices() -> None:
    long = pd.DataFrame(
        {
            "store_id": ["S1", "S1"],
            "item_id": ["A", "A"],
            "d": ["d_1", "d_2"],
            "units": [1, 2],
            "sell_price": [1.5, 1.75],
        }
    )
    grid = make_grid(long, n_days=2, value="sell_price")
    assert grid.loc["S1/A"].tolist() == [1.5, 1.75]


def test_calendar_features_describe_each_day() -> None:
    cal = calendar_features(make_calendar())
    assert cal.index[0] == 1
    assert cal.index[-1] == N_DAYS
    assert cal.loc[1, "dow"] == 5
    assert cal.loc[1, "month"] == 1
    assert cal.loc[1, "event"] == 0
    assert cal.loc[50, "event"] == 1
    assert cal.loc[50, "snap_CA"] == 1


def test_series_states_come_from_the_store_prefix() -> None:
    assert series_states(["CA_1/FOODS_1_001", "WI_3/HOBBIES_1_002"]) == ["CA", "WI"]


def test_rows_hold_origin_features_and_target_day_facts() -> None:
    values, prices, cal, states = make_inputs()
    rows = build_rows(values, prices, cal, states, origin=50, horizon=14)
    assert len(rows) == 2 * 14

    row = rows[(rows["series_idx"] == 0) & (rows["h"] == 1)].iloc[0]
    assert row["target_day"] == 51
    assert row["y"] == 51.0
    assert row["last_day"] == 50.0
    assert row["price"] == 2.0
    assert row["price_ratio"] == pytest.approx(1.0)
    assert row["dow"] == (5 + 51 - 1) % 7


def test_rows_contain_every_feature_column() -> None:
    values, prices, cal, states = make_inputs()
    rows = build_rows(values, prices, cal, states, origin=50, horizon=14)
    assert set(FEATURE_COLUMNS + ["y", "origin", "target_day", "series_idx"]) <= set(rows.columns)


def test_snap_follows_the_state_of_each_series() -> None:
    values, prices, cal, states = make_inputs()
    rows = build_rows(values, prices, cal, states, origin=45, horizon=14)
    on_day = rows[rows["target_day"] == 50].set_index("series_idx")
    assert on_day.loc[0, "snap"] == 1
    assert on_day.loc[1, "snap"] == 0
    assert on_day.loc[0, "event"] == 1


def test_price_ratio_compares_target_price_with_last_known_price() -> None:
    values, prices, cal, states = make_inputs()
    rows = build_rows(values, prices, cal, states, origin=50, horizon=14)
    row = rows[(rows["series_idx"] == 0) & (rows["target_day"] == 61)].iloc[0]
    assert row["price"] == 3.0
    assert row["price_ratio"] == pytest.approx(1.5)


def test_series_not_launched_by_the_origin_get_no_rows() -> None:
    values, prices, cal, states = make_inputs()
    rows = build_rows(values, prices, cal, states, origin=30, horizon=10)
    assert set(rows["series_idx"]) == {0}


def test_rows_beyond_the_available_days_are_rejected() -> None:
    values, prices, cal, states = make_inputs()
    with pytest.raises(ValueError):
        build_rows(values, prices, cal, states, origin=115, horizon=10)


def test_training_targets_never_pass_the_cutoff() -> None:
    values, prices, cal, states = make_inputs()
    table = training_table(
        values, prices, cal, states, cutoff=100, horizon=14, stride=7, first_origin=20
    )
    assert table["target_day"].max() <= 100
    assert table["origin"].max() <= 100 - 14
    assert (table["origin"] + table["h"] == table["target_day"]).all()


def test_training_rows_do_not_change_when_the_future_changes() -> None:
    values, prices, cal, states = make_inputs()
    args = {"cutoff": 100, "horizon": 14, "stride": 7, "first_origin": 20}
    before = training_table(values, prices, cal, states, **args)

    values[:, 100:] = 1e9
    prices[:, 100:] = 1e9
    after = training_table(values, prices, cal, states, **args)

    pd.testing.assert_frame_equal(before, after)


def test_cutoff_beyond_the_data_is_rejected() -> None:
    values, prices, cal, states = make_inputs()
    with pytest.raises(ValueError):
        training_table(values, prices, cal, states, cutoff=N_DAYS + 1)


def test_cutoff_too_early_for_any_origin_is_rejected() -> None:
    values, prices, cal, states = make_inputs()
    with pytest.raises(ValueError):
        training_table(values, prices, cal, states, cutoff=20, horizon=14, first_origin=20)
