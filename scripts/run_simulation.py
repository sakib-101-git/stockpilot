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
from ml.lgbm import fit
from ml.lgbm import forecast_future as lgbm_forecast_future
from ml.quantiles import fit_quantile
from ml.simulation import N_PER_TIER, select_stratified_sample, supplier_terms_for_sample

ROOT = Path(__file__).resolve().parents[1]
REFRESH_EVERY = 28
SIM_DAYS = 365
MIN_HISTORY = 56


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
    print(f"got supplier terms for {len(terms)} products")

    n_days = values.shape[1]
    sim_start_day = n_days - SIM_DAYS
    cal = calendar_features(calendar)
    states = [name.split("/")[0][:2] for name in series_names]

    print(f"\ntotal days available: {n_days}, sim_start_day: {sim_start_day}")

    # --- Single-product smoke test: confirm training + forecasting works
    # for one refresh point before scaling to all 15 products and 13 refreshes.
    test_idx = selected[0]
    test_name = sample_names[0]
    print(f"\nsmoke-testing on: {test_name} (row {test_idx})")

    origin = sim_start_day
    table = training_table(
        values, prices, cal, states, cutoff=origin, horizon=REFRESH_EVERY
    )
    print(f"training table rows: {len(table)}")

    model = fit(table, weighted=True)
    quantile_model = fit_quantile(table, q=0.9, weighted=False)
    print("trained point and quantile models")

    point, keep = lgbm_forecast_future(
        model, values, prices, cal, states, origin, REFRESH_EVERY, MIN_HISTORY
    )
    print(f"forecast shape: {point.shape}, eligible rows: {len(keep)}")
    print(f"is test_idx eligible? {test_idx in keep}")
    if test_idx in keep:
        row = keep.index(test_idx)
        print(f"first-day point forecast for {test_name}: {point[row, 0]:.2f}")


if __name__ == "__main__":
    main()