import numpy as np
import pandas as pd
import pytest

from ml.coldstart import (
    LGBM_NAME,
    choose_series,
    cold_start_quantile,
    hide_history,
    mean_and_count,
    peer_groups,
    peer_level,
    peer_ratio_quantile,
    shrunk_level,
    simulate,
)
from ml.features import calendar_features

N_DAYS = 300
SMALL = {
    "n_estimators": 5,
    "min_child_samples": 5,
    "num_leaves": 7,
    "n_jobs": 1,
    "deterministic": True,
}


def make_inputs():
    rng = np.random.default_rng(0)
    values = rng.poisson(2.0, size=(12, N_DAYS)).astype(float)
    prices = np.full((12, N_DAYS), 2.0)
    event = [None] * N_DAYS
    event[49] = "Cultural"
    cal = calendar_features(
        pd.DataFrame(
            {
                "d": [f"d_{i}" for i in range(1, N_DAYS + 1)],
                "date": pd.date_range("2011-01-29", periods=N_DAYS),
                "event_type_1": event,
                "snap_CA": [0] * N_DAYS,
                "snap_TX": [0] * N_DAYS,
                "snap_WI": [0] * N_DAYS,
            }
        )
    )
    names = [f"CA_1/FOODS_1_{i:03d}" for i in range(6)] + [
        f"TX_1/FOODS_1_{i:03d}" for i in range(6)
    ]
    return values, prices, cal, ["CA"] * 6 + ["TX"] * 6, peer_groups(names)


def test_peer_groups_combine_store_and_category() -> None:
    groups = peer_groups(["CA_1/FOODS_1_046", "TX_1/HOBBIES_2_119"])
    assert groups.tolist() == ["CA_1/FOODS", "TX_1/HOBBIES"]


def test_mean_and_count_ignore_missing_days() -> None:
    mean, count = mean_and_count(np.array([[1.0, np.nan, 3.0], [np.nan, np.nan, np.nan]]))
    assert mean[0] == 2.0
    assert np.isnan(mean[1])
    assert count.tolist() == [2, 0]


def test_peer_level_skips_the_series_itself_and_new_series() -> None:
    history = np.array(
        [
            np.full(120, 2.0),
            np.full(120, 4.0),
            np.full(120, 6.0),
            np.r_[np.full(115, np.nan), np.full(5, 100.0)],
        ]
    )
    level = peer_level(history, np.full(4, "g"))
    assert level.tolist() == pytest.approx([5.0, 4.0, 3.0, 4.0])


def test_shrunk_level_blends_own_history_with_peers() -> None:
    history = np.array(
        [
            np.full(120, 4.0),
            np.r_[np.full(113, np.nan), np.full(7, 10.0)],
            np.full(120, np.nan),
        ]
    )
    groups = np.full(3, "g")
    assert shrunk_level(history, groups, k0=7).tolist() == pytest.approx([4.0, 7.0, 4.0])
    assert shrunk_level(history, groups, k0=0).tolist() == pytest.approx([4.0, 10.0, 4.0])


def test_peer_ratio_quantile_pools_peers_in_shape() -> None:
    history = np.array([np.tile([0.0, 0.0, 0.0, 4.0], 30), np.full(120, 2.0)])
    groups = np.full(2, "g")
    assert peer_ratio_quantile(history, groups, 1.0).tolist() == pytest.approx([4.0, 4.0])
    assert peer_ratio_quantile(history, groups, 0.5).tolist() == pytest.approx([1.0, 1.0])


def test_cold_start_quantile_scales_peer_shape_by_the_level() -> None:
    history = np.array(
        [
            np.tile([0.0, 0.0, 0.0, 4.0], 30),
            np.full(120, 2.0),
            np.r_[np.full(113, np.nan), np.full(7, 10.0)],
        ]
    )
    upper = cold_start_quantile(history, np.full(3, "g"), horizon=5, q=1.0, k0=0)
    assert upper.shape == (3, 5)
    assert upper[2].tolist() == pytest.approx([40.0] * 5)


def test_hide_history_only_changes_chosen_rows_before_the_keep_window() -> None:
    values, prices = np.ones((3, 100)), np.full((3, 100), 2.0)
    hidden_v, hidden_p = hide_history(values, prices, np.array([1]), origin=80, keep_days=10)

    assert np.isnan(hidden_v[1, :70]).all()
    assert not np.isnan(hidden_v[1, 70:]).any()
    assert np.isnan(hidden_p[1, :70]).all()
    assert (~np.isnan(hidden_v[1, :80])).sum() == 10
    assert not np.isnan(hidden_v[[0, 2]]).any()
    assert not np.isnan(values).any()


def test_choose_series_is_seeded_and_skips_short_histories() -> None:
    values = np.ones((9, 200))
    values[3, :150] = np.nan
    first = choose_series(values, origin=180, fraction=0.5, seed=1)
    again = choose_series(values, origin=180, fraction=0.5, seed=1)
    assert first.tolist() == again.tolist()
    assert len(first) == 4
    assert 3 not in first
    assert first.tolist() == sorted(first.tolist())


def test_simulation_scores_every_method_for_every_keep_window() -> None:
    values, prices, cal, states, groups = make_inputs()
    point, interval = simulate(
        values, prices, cal, states, groups, 250, 0, keep_days=(7, 28), k0s=(7,), params=SMALL
    )
    assert set(point["method"]) == {"own history mean", "shrunk k0=7", LGBM_NAME}
    assert set(interval["method"]) == {"own history 90%", "peer shape k0=7"}
    assert set(point["keep_days"]) == {7, 28}
    assert (point["n_series"] == 2).all()
    assert interval["above_upper"].between(0, 1).all()


def test_hidden_history_cannot_influence_any_forecast() -> None:
    values, prices, cal, states, groups = make_inputs()
    kwargs = {"origin": 250, "seed": 0, "keep_days": (7, 28), "k0s": (7,), "params": SMALL}
    point, interval = simulate(values, prices, cal, states, groups, **kwargs)

    rows = choose_series(values, origin=250, fraction=0.2, seed=0)
    changed = values.copy()
    changed[rows, :222] = 1e9
    point_2, interval_2 = simulate(changed, prices, cal, states, groups, **kwargs)

    # RMSSE is left out: its scale deliberately uses the true full history.
    pd.testing.assert_frame_equal(point[["RMSE", "bias"]], point_2[["RMSE", "bias"]])
    columns = ["pinball_90", "above_upper", "mean_upper"]
    pd.testing.assert_frame_equal(interval[columns], interval_2[columns])


def test_keep_days_longer_than_the_horizon_are_rejected() -> None:
    values, prices, cal, states, groups = make_inputs()
    with pytest.raises(ValueError, match="horizon"):
        simulate(values, prices, cal, states, groups, 250, 0, keep_days=(56,), params=SMALL)
