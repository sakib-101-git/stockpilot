"""Tests for feature drift detection.

Uses small synthetic grids with a known, deliberate shift (or deliberate
absence of one) rather than real tenant data, so the expected result is
known in advance rather than discovered.
"""

import numpy as np

from app.services.drift import build_feature_snapshot


def _make_values(n_series: int, n_days: int, level: float, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.poisson(level, size=(n_series, n_days)).astype(float)


def test_build_feature_snapshot_returns_one_row_per_series() -> None:
    values = _make_values(n_series=10, n_days=100, level=5.0)
    snapshot = build_feature_snapshot(values, origin=60)
    assert len(snapshot) == 10


def test_build_feature_snapshot_mean_7_reflects_recent_level() -> None:
    values = _make_values(n_series=5, n_days=100, level=10.0)
    snapshot = build_feature_snapshot(values, origin=60)
    # with level=10 poisson, mean_7 should be roughly in that range
    assert 5.0 < snapshot["mean_7"].mean() < 15.0
