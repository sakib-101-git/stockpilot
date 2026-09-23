"""Policy simulation: Stockpilot's forecast-driven reorder point vs. a
naive moving-average baseline, over 15 real M5 products stratified by
speed tier, across the most recent 365 days.

See docs/decisions/ for the design (data source, refresh cadence, and the
known asymmetry between how each policy updates between refresh points).
"""

from pathlib import Path

import numpy as np
import pandas as pd

from ml.backtest import make_grid
from ml.features import calendar_features, training_table
from ml.lgbm import forecast_future as lgbm_forecast_future
from ml.quantiles import fit_quantile
from ml.simulation import (
    N_PER_TIER,
    naive_reorder_point,
    select_stratified_sample,
    simulate_policy,
    supplier_terms_for_sample,
)

ROOT = Path(__file__).resolve().parents[1]
REFRESH_EVERY = 28
SIM_DAYS = 365
MIN_HISTORY = 56


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


def main() -> None:
    sales = pd.read_parquet(ROOT / "data" / "processed" / "sales.parquet")
    calendar = pd.read_parquet(ROOT / "data" / "processed" / "calendar.parquet")

    grid = make_grid(sales)
    values = grid.to_numpy()
    prices = make_grid(sales, value="sell_price").to_numpy(dtype=float)
    series_names = grid.index.tolist()

    selected = select_stratified_sample(values)
    sample_names = [series_names[i] for i in selected]
    print(f"selected {len(sample_names)} products ({N_PER_TIER} per tier)")

    terms = supplier_terms_for_sample(sales, sample_names)
    missing = [n for n in sample_names if n not in terms]
    if missing:
        raise RuntimeError(f"no supplier terms for: {missing}")

    n_days = values.shape[1]
    sim_start_day = n_days - SIM_DAYS
    cal = calendar_features(calendar)
    states = [name.split("/")[0][:2] for name in series_names]

    n_refreshes = SIM_DAYS // REFRESH_EVERY
    refresh_origins = [sim_start_day + i * REFRESH_EVERY for i in range(n_refreshes)]
    print(f"running {n_refreshes} refreshes from day {sim_start_day}, every {REFRESH_EVERY} days")

    # index selected -> its per-refresh upper-bound forecast array
    per_product_refresh_upper: dict[int, dict[int, np.ndarray]] = {idx: {} for idx in selected}

    for refresh_idx, origin in enumerate(refresh_origins):
        print(f"\n--- refresh {refresh_idx + 1}/{n_refreshes} (origin day {origin}) ---")
        table = training_table(values, prices, cal, states, cutoff=origin, horizon=REFRESH_EVERY)
        upper_model = fit_quantile(table, q=0.9, weighted=False)
        upper, keep = lgbm_forecast_future(
            upper_model, values, prices, cal, states, origin, REFRESH_EVERY, MIN_HISTORY
        )
        keep_pos = {idx: pos for pos, idx in enumerate(keep)}
        for idx in selected:
            if idx in keep_pos:
                per_product_refresh_upper[idx][refresh_idx] = upper[keep_pos[idx]]
        print(f"trained, {len(keep)} eligible series")

    print("\n=== running simulations ===")
    results = []
    for idx, name in zip(selected, sample_names, strict=True):
        link = terms[name]
        lead_time_window = max(1, int(np.ceil(link.lead_time_days_mean + link.lead_time_days_std)))
        moq, pack_size = link.moq, link.pack_size

        sim_daily_sales = np.nan_to_num(
            values[idx, sim_start_day : sim_start_day + SIM_DAYS], nan=0.0
        )
        window_before = values[idx, max(0, sim_start_day - 28) : sim_start_day]
        avg_daily = np.nanmean(window_before) if not np.all(np.isnan(window_before)) else 0.0
        initial_stock = float(avg_daily) * 14

        forecast_fn = build_forecast_reorder_fn(
            per_product_refresh_upper[idx], lead_time_window, REFRESH_EVERY
        )
        forecast_result = simulate_policy(
            sim_daily_sales,
            forecast_fn,
            lead_time_window,
            moq,
            pack_size,
            initial_stock,
            policy_name="forecast",
        )

        def naive_fn(day: int, _idx=idx, _lt=lead_time_window) -> float:
            window_data = np.nan_to_num(
                values[_idx, max(0, sim_start_day + day - 28) : sim_start_day + day], nan=0.0
            )
            return naive_reorder_point(window_data, _lt)

        naive_result = simulate_policy(
            sim_daily_sales,
            naive_fn,
            lead_time_window,
            moq,
            pack_size,
            initial_stock,
            policy_name="naive",
        )

        results.append((name, forecast_result, naive_result))
        print(
            f"{name}: forecast stockout_days={forecast_result.stockout_days}, "
            f"naive stockout_days={naive_result.stockout_days}"
        )

    print("\n=== SUMMARY ===")
    total_forecast_stockouts = sum(r[1].stockout_days for r in results)
    total_naive_stockouts = sum(r[2].stockout_days for r in results)
    total_forecast_unmet = sum(r[1].total_unmet_demand for r in results)
    total_naive_unmet = sum(r[2].total_unmet_demand for r in results)
    total_forecast_avg_stock = sum(r[1].avg_stock for r in results) / len(results)
    total_naive_avg_stock = sum(r[2].avg_stock for r in results) / len(results)

    print(
        f"Forecast policy: {total_forecast_stockouts} total stockout-days, "
        f"{total_forecast_unmet:.1f} total unmet demand, avg stock {total_forecast_avg_stock:.1f}"
    )
    print(
        f"Naive policy:    {total_naive_stockouts} total stockout-days, "
        f"{total_naive_unmet:.1f} total unmet demand, avg stock {total_naive_avg_stock:.1f}"
    )


if __name__ == "__main__":
    main()
