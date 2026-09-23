"""Policy simulation: compares Stockpilot's forecast-driven reorder point
against a naive moving-average baseline, over real M5 sales history, with
a day-by-day loop that simulates actual replenishment (so stock never goes
negative and stays in a realistic range, unlike the live-data path's known
limitation — see docs/decisions/0010-reorder-optimizer.md).
"""

from dataclasses import dataclass

import numpy as np

from ml.quantiles import speed_groups

N_PER_TIER = 5
TIERS = ("slow", "medium", "fast")
SAMPLE_SEED = 42


def select_stratified_sample(
    values: np.ndarray, window: int = 56, seed: int = SAMPLE_SEED
) -> list[int]:
    """Row indices of N_PER_TIER series from each speed tier, chosen by a
    fixed random seed within each tier — reproducible (same seed always
    gives the same result) without being biased toward however the input
    rows happen to be ordered (e.g. all from one store or category).
    """
    groups = speed_groups(values, window=window)
    rng = np.random.default_rng(seed)
    selected: list[int] = []
    for tier in TIERS:
        tier_indices = np.flatnonzero(groups == tier)
        chosen = rng.choice(tier_indices, size=min(N_PER_TIER, len(tier_indices)), replace=False)
        selected.extend(sorted(chosen.tolist()))
    return selected


def supplier_terms_for_sample(sales_df, series_names: list[str], seed: int = SAMPLE_SEED) -> dict:
    """Real supplier terms (cost, lead time, MOQ, pack size) for the given
    series, reusing Week 3's synthetic generation logic rather than
    inventing new numbers. Keyed by the full series name ('store_id/sku'),
    not sku alone — sku is only unique within a store, so two different
    stores can share a sku and must not collide.
    """
    from scripts.synth.generate import plan_links, plan_suppliers, summarize_products

    all_products = summarize_products(sales_df)
    wanted_pairs = {tuple(name.split("/", 1)) for name in series_names}
    mask = all_products.apply(lambda row: (row["store_id"], row["sku"]) in wanted_pairs, axis=1)
    sample_products = all_products[mask].reset_index(drop=True)

    rng = np.random.default_rng(seed)
    suppliers = plan_suppliers("Simulation Tenant", rng)
    links = plan_links(sample_products, suppliers, rng)

    # plan_links preserves sample_products' row order, so pair them up by
    # position rather than re-keying by sku, avoiding the same collision risk.
    terms_by_pair = {
        (row.store_id, row.sku): link
        for row, link in zip(sample_products.itertuples(), links, strict=True)
    }

    result = {}
    for name in series_names:
        store_id, sku = name.split("/", 1)
        pair = (store_id, sku)
        if pair in terms_by_pair:
            result[name] = terms_by_pair[pair]
    return result


def naive_reorder_point(
    recent_daily_sales: np.ndarray, lead_time_window_days: int, window: int = 28
) -> float:
    """Sum of a simple trailing moving-average daily demand over the
    lead-time window. The naive counterpart to Stockpilot's upper-bound-
    based reorder point — same lead-time buffering, no ML. Unlike the
    forecast-driven policy (frozen between 28-day refreshes), this updates
    every simulated day, since it costs nothing to recompute.
    """
    if len(recent_daily_sales) == 0:
        return 0.0
    avg_daily = float(np.mean(recent_daily_sales[-window:]))
    return avg_daily * lead_time_window_days


@dataclass
class SimulationResult:
    policy_name: str
    stockout_days: int
    total_unmet_demand: float
    avg_stock: float
    total_orders_placed: int
    total_units_ordered: int
    n_days: int


def simulate_policy(
    daily_sales: np.ndarray,
    reorder_point_fn,
    lead_time_days: int,
    moq: int,
    pack_size: int,
    initial_stock: float,
    policy_name: str = "policy",
) -> SimulationResult:
    """Day-by-day simulation: receive any order due today, apply real
    demand (clipped at available stock, never negative — the shortfall is
    recorded as unmet demand, not a negative stock balance), then reorder
    if stock has fallen below reorder_point_fn(day) and no order is
    currently in transit.

    Only one order may be in transit per product at a time — a second
    reorder trigger while one is pending is skipped, matching a small shop
    placing one purchase order at a time per product.
    """
    import math

    n_days = len(daily_sales)
    stock = float(initial_stock)
    pending_arrival_day: int | None = None
    pending_qty = 0

    stockout_days = 0
    total_unmet = 0.0
    stock_sum = 0.0
    total_orders = 0
    total_units_ordered = 0

    for day in range(n_days):
        if pending_arrival_day == day:
            stock += pending_qty
            pending_arrival_day = None
            pending_qty = 0

        demand = float(daily_sales[day])
        sold = min(stock, demand)
        unmet = demand - sold
        stock -= sold
        if unmet > 1e-9:
            stockout_days += 1
            total_unmet += unmet

        stock_sum += stock

        reorder_point = reorder_point_fn(day)
        if stock < reorder_point and pending_arrival_day is None:
            raw_need = max(0.0, reorder_point - stock)
            packs_needed = math.ceil(raw_need / pack_size) if raw_need > 0 else 0
            qty = max(packs_needed * pack_size, moq)
            pending_arrival_day = day + lead_time_days
            pending_qty = qty
            total_orders += 1
            total_units_ordered += qty

    return SimulationResult(
        policy_name=policy_name,
        stockout_days=stockout_days,
        total_unmet_demand=round(total_unmet, 2),
        avg_stock=round(stock_sum / n_days, 2) if n_days else 0.0,
        total_orders_placed=total_orders,
        total_units_ordered=total_units_ordered,
        n_days=n_days,
    )


def build_forecast_reorder_fn(
    refresh_upper_bounds: dict, lead_time_window: int, refresh_every: int
):
    """Stitches per-refresh 28-day upper-bound forecasts into one function
    covering the whole simulation: day d since a refresh uses that
    refresh's forecast for horizon day (d % refresh_every), summed over
    the next lead_time_window forecasted days from that point.
    """

    def reorder_point_fn(sim_day: int) -> float:
        refresh_idx = sim_day // refresh_every
        day_since_refresh = sim_day % refresh_every
        upper = refresh_upper_bounds.get(refresh_idx)
        if upper is None:
            return 0.0
        start = day_since_refresh
        end = min(start + lead_time_window, len(upper))
        if start >= len(upper):
            return float(upper[-1]) * lead_time_window
        return float(np.sum(upper[start:end]))

    return reorder_point_fn
