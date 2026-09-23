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


def test_supplier_terms_handles_same_sku_in_different_stores() -> None:
    """The real collision risk: sku is only unique within a store."""
    import pandas as pd

    from ml.simulation import supplier_terms_for_sample

    sales = pd.DataFrame(
        {
            "store_id": ["CA_1"] * 5 + ["TX_1"] * 5,
            "item_id": ["FOODS_1_001"] * 5 + ["FOODS_1_001"] * 5,
            "cat_id": ["FOODS"] * 10,
            "sell_price": [2.0] * 5 + [3.0] * 5,
            "units": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        }
    )
    names = ["CA_1/FOODS_1_001", "TX_1/FOODS_1_001"]

    terms = supplier_terms_for_sample(sales, names, seed=1)

    assert len(terms) == 2
    ca_cost = terms["CA_1/FOODS_1_001"].unit_cost
    tx_cost = terms["TX_1/FOODS_1_001"].unit_cost
    # Different avg_price per store (2.0 vs 3.0) must produce different costs
    assert ca_cost != tx_cost
