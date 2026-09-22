from datetime import date

import numpy as np
import pandas as pd
import pytest

from scripts.synth.generate import (
    plan_batches,
    plan_links,
    plan_opening_stock,
    plan_suppliers,
    summarize_products,
)


def make_products() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sku": ["FOODS_1_001", "HOBBIES_1_001"],
            "cat_id": ["FOODS", "HOBBIES"],
            "avg_price": [2.0, 10.0],
            "avg_daily_units": [4.0, 0.5],
        }
    )


def test_plan_suppliers_gives_two_or_three_with_unique_names() -> None:
    rng = np.random.default_rng(0)
    suppliers = plan_suppliers("CA_1 Store", rng)
    assert 2 <= len(suppliers) <= 3
    assert len({s.name for s in suppliers}) == len(suppliers)


def test_plan_links_derives_cost_from_price_and_lead_time_from_category() -> None:
    rng = np.random.default_rng(0)
    suppliers = plan_suppliers("CA_1 Store", rng)
    links = plan_links(make_products(), suppliers, rng)

    assert len(links) == 2
    foods = next(link for link in links if link.product_sku == "FOODS_1_001")
    assert foods.unit_cost == pytest.approx(1.2)
    assert 3 <= foods.lead_time_days_mean <= 7
    assert foods.lead_time_days_std == pytest.approx(round(foods.lead_time_days_mean * 0.20, 1))
    assert foods.moq in (1, 6, 12, 24)
    assert all(link.supplier_name in {s.name for s in suppliers} for link in links)


def test_plan_opening_stock_scales_with_average_daily_sales() -> None:
    rng = np.random.default_rng(0)
    stock = plan_opening_stock(make_products(), date(2016, 4, 25), rng)
    by_sku = {s.product_sku: s for s in stock}

    assert by_sku["FOODS_1_001"].quantity > by_sku["HOBBIES_1_001"].quantity
    assert by_sku["HOBBIES_1_001"].quantity >= 1
    assert all(s.occurred_on == date(2016, 4, 25) for s in stock)


def test_plan_batches_only_covers_foods_and_matches_stock_quantity() -> None:
    rng = np.random.default_rng(0)
    stock = plan_opening_stock(make_products(), date(2016, 4, 25), rng)
    batches = plan_batches(make_products(), stock, rng)

    assert len(batches) == 1
    batch = batches[0]
    assert batch.product_sku == "FOODS_1_001"
    stock_qty = next(s.quantity for s in stock if s.product_sku == "FOODS_1_001")
    assert batch.quantity == stock_qty
    assert batch.received_on == date(2016, 4, 25)
    assert 7 <= (batch.expires_on - batch.received_on).days <= 60


def test_generation_is_reproducible_with_the_same_seed() -> None:
    products = make_products()
    rng1, rng2 = np.random.default_rng(7), np.random.default_rng(7)
    links1 = plan_links(products, plan_suppliers("Shop", rng1), rng1)
    links2 = plan_links(products, plan_suppliers("Shop", rng2), rng2)
    assert [link.unit_cost for link in links1] == [link.unit_cost for link in links2]
    assert [link.lead_time_days_mean for link in links1] == [
        link.lead_time_days_mean for link in links2
    ]


def test_summarize_products_averages_per_store_and_item() -> None:
    sales = pd.DataFrame(
        {
            "store_id": ["CA_1", "CA_1", "CA_1", "TX_1"],
            "item_id": ["A", "A", "B", "A"],
            "cat_id": ["FOODS", "FOODS", "HOBBIES", "FOODS"],
            "sell_price": [1.0, 3.0, 5.0, 2.0],
            "units": [2, 4, 0, 10],
        }
    )
    summary = summarize_products(sales).set_index(["store_id", "sku"])

    assert summary.loc[("CA_1", "A"), "avg_price"] == pytest.approx(2.0)
    assert summary.loc[("CA_1", "A"), "avg_daily_units"] == pytest.approx(3.0)
    assert summary.loc[("CA_1", "B"), "cat_id"] == "HOBBIES"
    assert summary.loc[("TX_1", "A"), "avg_price"] == pytest.approx(2.0)
