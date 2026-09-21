import numpy as np
import pandas as pd

from ml.backtest import HORIZON, MIN_HISTORY, split_fold
from ml.features import training_table
from ml.lgbm import fit, forecast
from ml.metrics import coverage, mean_width, pinball

QUANTILES = (0.1, 0.9)


def empirical_quantile(history: np.ndarray, horizon: int, q: float, window: int = 56) -> np.ndarray:
    """Each series' own q-quantile of its last `window` days, repeated per horizon day."""
    recent = history[:, -window:]
    level = np.nanquantile(recent, q, axis=1)
    return np.tile(level[:, None], (1, horizon))


def fit_quantile(train_table: pd.DataFrame, q: float, weighted: bool = False, params=None):
    """LightGBM model for the q-quantile, trained with pinball loss."""
    quantile_params = {"objective": "quantile", "alpha": q, **(params or {})}
    return fit(train_table, weighted=weighted, params=quantile_params, weight_power=0.5)


def quantile_forecasts(
    models,
    values: np.ndarray,
    prices: np.ndarray,
    cal: pd.DataFrame,
    states: list[str],
    origin: int,
    horizon: int = HORIZON,
    min_history: int = MIN_HISTORY,
) -> tuple[np.ndarray, float]:
    """Forecast grids for each model, sorted so lower quantiles never exceed higher ones.

    Returns an array of shape (models, series, days) and the share of cells where
    the lowest and highest models disagreed before sorting.
    """
    raw = np.stack(
        [forecast(m, values, prices, cal, states, origin, horizon, min_history) for m in models]
    )
    crossed = float((raw[0] > raw[-1]).mean())
    return np.sort(raw, axis=0), crossed


def _score(origin, name, n_series, grids, actual, quantiles, crossed) -> dict:
    lower, upper = grids[0], grids[-1]
    row = {
        "origin": origin,
        "method": name,
        "n_series": n_series,
        "coverage": coverage(lower, upper, actual),
        "width": mean_width(lower, upper),
        "zero_upper": float((upper == 0).mean()),
        "crossed": crossed,
    }
    for q, grid in zip(quantiles, grids, strict=True):
        row[f"pinball_{round(q * 100)}"] = pinball(grid, actual, q)
    return row


def empirical_backtest(
    values: np.ndarray,
    origins: tuple[int, ...],
    quantiles: tuple[float, ...] = QUANTILES,
    window: int = 112,
    name: str | None = None,
    horizon: int = HORIZON,
    min_history: int = MIN_HISTORY,
) -> pd.DataFrame:
    """Score the each-series-own-history interval on every origin."""
    name = name or f"empirical {window}d"
    rows = []
    for origin in origins:
        history, actual = split_fold(values, origin, horizon, min_history)
        grids = np.stack([empirical_quantile(history, horizon, q, window) for q in quantiles])
        rows.append(_score(origin, name, history.shape[0], grids, actual, quantiles, 0.0))
    return pd.DataFrame(rows)


def quantile_backtest(
    values: np.ndarray,
    prices: np.ndarray,
    cal: pd.DataFrame,
    states: list[str],
    origins: tuple[int, ...],
    quantiles: tuple[float, ...] = QUANTILES,
    weighted: bool = False,
    params: dict | None = None,
    name: str = "LightGBM quantile",
    horizon: int = HORIZON,
    min_history: int = MIN_HISTORY,
) -> pd.DataFrame:
    """One model per quantile and per origin, trained only on targets up to that origin."""
    rows = []
    for origin in origins:
        table = training_table(values, prices, cal, states, cutoff=origin, horizon=horizon)
        models = [fit_quantile(table, q, weighted, params) for q in quantiles]
        history, actual = split_fold(values, origin, horizon, min_history)
        grids, crossed = quantile_forecasts(
            models, values, prices, cal, states, origin, horizon, min_history
        )
        rows.append(_score(origin, name, history.shape[0], grids, actual, quantiles, crossed))
    return pd.DataFrame(rows)


def speed_groups(history: np.ndarray, window: int = 56) -> np.ndarray:
    """Label each series slow, medium or fast by its average daily sales over the last days."""
    level = pd.Series(np.nanmean(history[:, -window:], axis=1))
    speed = pd.qcut(level.rank(method="first"), 3, labels=["slow", "medium", "fast"])
    return speed.to_numpy()


def interval_breakdown(
    lower: np.ndarray, upper: np.ndarray, actual: np.ndarray, groups: np.ndarray
) -> pd.DataFrame:
    """Coverage and both miss rates for each group of series."""
    rows = []
    for group in pd.unique(groups):
        mask = groups == group
        lo, hi, act = lower[mask], upper[mask], actual[mask]
        rows.append(
            {
                "group": group,
                "n_series": int(mask.sum()),
                "coverage": coverage(lo, hi, act),
                "below_lower": float((act < lo).mean()),
                "above_upper": float((act > hi).mean()),
                "width": mean_width(lo, hi),
                "lower_is_zero": float((lo == 0).mean()),
            }
        )
    return pd.DataFrame(rows)
