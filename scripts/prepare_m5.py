"""Build the Stockpilot sales dataset from the raw M5 files.

Reads:  data/raw/m5/sales_train_evaluation.csv, calendar.csv, sell_prices.csv
Writes: data/processed/sales.parquet, data/processed/calendar.parquet
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "m5"
OUT = ROOT / "data" / "processed"

STORES = ["CA_1", "TX_1", "WI_1"]
ITEMS_PER_CATEGORY = 50
SEED = 42
N_DAYS = 1941
ID_COLS = ["item_id", "dept_id", "cat_id", "store_id", "state_id"]


def pick_items() -> pd.Series:
    """Choose 50 items per category with a fixed seed (stratified sample)."""
    ids = pd.read_csv(
        RAW / "sales_train_evaluation.csv",
        usecols=["item_id", "cat_id", "store_id", "state_id"],
    )
    items = ids[["item_id", "cat_id"]].drop_duplicates()
    sample = items.groupby("cat_id").sample(n=ITEMS_PER_CATEGORY, random_state=SEED)
    return sample["item_id"]


def load_sales(item_ids: pd.Series) -> pd.DataFrame:
    """Load sales for our stores and items, converted from wide to long."""
    day_cols = {f"d_{i}": "int16" for i in range(1, N_DAYS + 1)}
    sales = pd.read_csv(RAW / "sales_train_evaluation.csv", dtype=day_cols)
    keep = sales["store_id"].isin(STORES) & sales["item_id"].isin(item_ids)
    sales = sales[keep]
    d_cols = [c for c in sales.columns if c.startswith("d_")]
    return sales.melt(id_vars=ID_COLS, value_vars=d_cols, var_name="d", value_name="units")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    item_ids = pick_items()
    long = load_sales(item_ids)

    calendar = pd.read_csv(RAW / "calendar.csv")
    calendar["date"] = pd.to_datetime(calendar["date"])
    long = long.merge(calendar[["d", "date", "wm_yr_wk"]], on="d", how="left")

    prices = pd.read_csv(RAW / "sell_prices.csv")
    prices = prices[prices["store_id"].isin(STORES) & prices["item_id"].isin(item_ids)]
    keys = ["store_id", "item_id", "wm_yr_wk"]
    assert not prices.duplicated(subset=keys).any(), "duplicate price keys"
    long = long.merge(prices, on=keys, how="left")

    # No price means the item was not on sale yet, so it is not a real zero-demand day.
    long = long.sort_values(["store_id", "item_id", "date"])
    long = long[long["sell_price"].notna()].reset_index(drop=True)

    long.to_parquet(OUT / "sales.parquet", index=False)
    calendar.to_parquet(OUT / "calendar.parquet", index=False)

    print(f"rows:            {len(long):,}")
    print(f"series:          {long.groupby(['store_id', 'item_id']).ngroups}")
    print(f"date range:      {long['date'].min().date()} -> {long['date'].max().date()}")
    print(f"zero-sales days: {(long['units'] == 0).mean():.1%}")


if __name__ == "__main__":
    main()
