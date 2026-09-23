import numpy as np

from ml.simulation import N_PER_TIER, TIERS, select_stratified_sample


def _fake_values(n_series: int = 30, n_days: int = 100) -> np.ndarray:
    """Synthetic grid with a clear slow/medium/fast split by construction."""
    rng = np.random.default_rng(0)
    tiers_per_series = np.tile([1, 5, 20], n_series // 3 + 1)[:n_series]
    values = np.stack([rng.poisson(level, n_days).astype(float) for level in tiers_per_series])
    return values


def test_select_stratified_sample_returns_n_per_tier_times_tier_count() -> None:
    values = _fake_values()
    selected = select_stratified_sample(values)
    assert len(selected) == N_PER_TIER * len(TIERS)


def test_select_stratified_sample_is_reproducible_with_the_same_seed() -> None:
    values = _fake_values()
    first = select_stratified_sample(values, seed=7)
    second = select_stratified_sample(values, seed=7)
    assert first == second


def test_select_stratified_sample_differs_with_a_different_seed() -> None:
    values = _fake_values(n_series=60)
    first = select_stratified_sample(values, seed=1)
    second = select_stratified_sample(values, seed=2)
    assert first != second


def test_select_stratified_sample_returns_unique_indices() -> None:
    values = _fake_values()
    selected = select_stratified_sample(values)
    assert len(selected) == len(set(selected))
