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
