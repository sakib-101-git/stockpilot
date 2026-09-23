"""Policy simulation: compares Stockpilot's forecast-driven reorder point
against a naive moving-average baseline, over real M5 sales history, with
a day-by-day loop that simulates actual replenishment (so stock never goes
negative and stays in a realistic range, unlike the live-data path's known
limitation — see docs/decisions/0010-reorder-optimizer.md).
"""

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
