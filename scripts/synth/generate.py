"""Synthetic supplier, cost, lead-time and stock data for the M5 sample.

M5 has no suppliers, costs, lead times, stock levels or shelf life. This
module generates plausible values so the app has something to operate on.
Every number here is an assumption, not observed data — see
docs/decisions/0007-synthetic-supply-data.md.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

SEED = 42
SUPPLIERS_PER_TENANT = (2, 3)
COST_MARGIN = 0.60
LEAD_TIME_DAYS = {"FOODS": (3, 7), "HOUSEHOLD": (5, 10), "HOBBIES": (5, 10)}
LEAD_TIME_STD_FRACTION = 0.20
PACK_SIZES = (1, 6, 12, 24)
MOQ_OPTIONS = (1, 6, 12, 24)
OPENING_STOCK_WEEKS = (2, 4)
SHELF_LIFE_DAYS = {"FOODS": (7, 60)}


@dataclass(frozen=True)
class SupplierPlan:
    name: str
    contact_email: str


@dataclass(frozen=True)
class LinkPlan:
    product_sku: str
    supplier_name: str
    unit_cost: float
    lead_time_days_mean: float
    lead_time_days_std: float
    moq: int
    pack_size: int


@dataclass(frozen=True)
class StockPlan:
    product_sku: str
    quantity: int
    occurred_on: date


@dataclass(frozen=True)
class BatchPlan:
    product_sku: str
    quantity: int
    received_on: date
    expires_on: date


def plan_suppliers(tenant_name: str, rng: np.random.Generator) -> list[SupplierPlan]:
    n = rng.integers(SUPPLIERS_PER_TENANT[0], SUPPLIERS_PER_TENANT[1] + 1)
    slug = tenant_name.lower().replace(" ", "-")
    return [
        SupplierPlan(
            name=f"{tenant_name} Vendor {i + 1}", contact_email=f"orders@{slug}-v{i + 1}.example"
        )
        for i in range(n)
    ]


def plan_links(
    products: pd.DataFrame, suppliers: list[SupplierPlan], rng: np.random.Generator
) -> list[LinkPlan]:
    """One supplier per product, cost and lead time derived from category and price."""
    plans = []
    for row in products.itertuples():
        supplier = suppliers[rng.integers(0, len(suppliers))]
        lo, hi = LEAD_TIME_DAYS.get(row.cat_id, (5, 10))
        mean = round(float(rng.uniform(lo, hi)), 1)
        plans.append(
            LinkPlan(
                product_sku=row.sku,
                supplier_name=supplier.name,
                unit_cost=round(row.avg_price * COST_MARGIN, 2),
                lead_time_days_mean=mean,
                lead_time_days_std=round(mean * LEAD_TIME_STD_FRACTION, 1),
                moq=int(rng.choice(MOQ_OPTIONS)),
                pack_size=int(rng.choice(PACK_SIZES)),
            )
        )
    return plans


def plan_opening_stock(
    products: pd.DataFrame, start_date: date, rng: np.random.Generator
) -> list[StockPlan]:
    """Opening stock sized as 2-4 weeks of each product's historical average daily sales."""
    weeks = rng.uniform(OPENING_STOCK_WEEKS[0], OPENING_STOCK_WEEKS[1], size=len(products))
    quantities = np.maximum(1, np.round(products["avg_daily_units"].to_numpy() * 7 * weeks)).astype(
        int
    )
    return [
        StockPlan(product_sku=row.sku, quantity=int(q), occurred_on=start_date)
        for row, q in zip(products.itertuples(), quantities, strict=True)
    ]


def plan_batches(
    products: pd.DataFrame,
    opening_stock: list[StockPlan],
    rng: np.random.Generator,
) -> list[BatchPlan]:
    """One batch per opening-stock receipt, FOODS products only."""
    stock_by_sku = {s.product_sku: s for s in opening_stock}
    plans = []
    for row in products.itertuples():
        if row.cat_id != "FOODS":
            continue
        stock = stock_by_sku[row.sku]
        lo, hi = SHELF_LIFE_DAYS["FOODS"]
        shelf_days = int(rng.integers(lo, hi + 1))
        plans.append(
            BatchPlan(
                product_sku=row.sku,
                quantity=stock.quantity,
                received_on=stock.occurred_on,
                expires_on=stock.occurred_on + timedelta(days=shelf_days),
            )
        )
    return plans
