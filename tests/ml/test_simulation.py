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


def test_simulate_policy_matches_hand_traced_scenario() -> None:
    from ml.simulation import simulate_policy

    daily_sales = np.array([5.0] * 10)
    result = simulate_policy(
        daily_sales,
        reorder_point_fn=lambda day: 10.0,
        lead_time_days=2,
        moq=1,
        pack_size=1,
        initial_stock=20.0,
        policy_name="test",
    )

    assert result.stockout_days == 2
    assert result.total_unmet_demand == 10.0
    assert result.avg_stock == 3.5
    assert result.total_orders_placed == 4
    assert result.total_units_ordered == 30


def test_simulate_policy_never_stocks_out_with_ample_initial_stock_and_no_reorder_needed() -> None:
    from ml.simulation import simulate_policy

    daily_sales = np.array([1.0] * 20)
    result = simulate_policy(
        daily_sales,
        reorder_point_fn=lambda day: 0.0,
        lead_time_days=3,
        moq=1,
        pack_size=1,
        initial_stock=1000.0,
        policy_name="test",
    )

    assert result.stockout_days == 0
    assert result.total_unmet_demand == 0.0
    assert result.total_orders_placed == 0


def test_build_forecast_reorder_fn_uses_the_correct_horizon_day() -> None:
    from ml.simulation import build_forecast_reorder_fn

    # Refresh 0 forecasts days 1..5 as [10, 20, 30, 40, 50].
    # lead_time_window=2, so day 0 since refresh sums forecast[0:2] = 10+20=30.
    refresh_upper = {0: np.array([10.0, 20.0, 30.0, 40.0, 50.0])}
    fn = build_forecast_reorder_fn(refresh_upper, lead_time_window=2, refresh_every=5)

    assert fn(0) == 30.0  # forecast[0:2]
    assert fn(1) == 50.0  # forecast[1:3] = 20+30
    assert fn(2) == 70.0  # forecast[2:4] = 30+40


def test_build_forecast_reorder_fn_moves_to_the_next_refresh_correctly() -> None:
    from ml.simulation import build_forecast_reorder_fn

    refresh_upper = {
        0: np.array([10.0, 10.0, 10.0, 10.0, 10.0]),
        1: np.array([99.0, 99.0, 99.0, 99.0, 99.0]),
    }
    fn = build_forecast_reorder_fn(refresh_upper, lead_time_window=1, refresh_every=5)

    assert fn(4) == 10.0  # last day of refresh 0's window
    assert fn(5) == 99.0  # sim_day 5 -> refresh_idx 1, day_since_refresh 0


def test_build_forecast_reorder_fn_clamps_at_the_end_of_the_forecast_array() -> None:
    from ml.simulation import build_forecast_reorder_fn

    # lead_time_window=3 but only 2 days remain in the forecast window;
    # should sum what's available, not index out of range.
    refresh_upper = {0: np.array([5.0, 5.0, 5.0])}
    fn = build_forecast_reorder_fn(refresh_upper, lead_time_window=3, refresh_every=3)

    assert fn(1) == 10.0  # forecast[1:4] clamped to forecast[1:3] = indices 1,2 = 5.0+5.0


def test_build_forecast_reorder_fn_returns_zero_for_a_missing_refresh() -> None:
    from ml.simulation import build_forecast_reorder_fn

    fn = build_forecast_reorder_fn({}, lead_time_window=2, refresh_every=5)
    assert fn(0) == 0.0
