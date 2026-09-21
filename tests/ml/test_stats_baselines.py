import numpy as np

from ml.stats_baselines import STATS_BASELINES, to_long


def test_to_long_skips_days_before_launch() -> None:
    history = np.array([[np.nan, 2.0, 3.0], [1.0, 1.0, 1.0]])
    long = to_long(history)
    assert len(long) == 5
    assert long.loc[long["unique_id"] == "s0", "y"].tolist() == [2.0, 3.0]


def test_forecasters_return_one_row_per_series_and_no_negatives() -> None:
    rng = np.random.default_rng(0)
    history = rng.poisson(1.0, size=(3, 70)).astype(float)
    for name, forecaster in STATS_BASELINES.items():
        forecast = forecaster(history, 7)
        assert forecast.shape == (3, 7), name
        assert (forecast >= 0).all(), name
