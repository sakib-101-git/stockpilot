"""Forecasts for new products, borrowing from similar products until history builds up."""

import numpy as np
import pandas as pd

from ml.backtest import HORIZON
from ml.features import training_table
from ml.lgbm import fit, forecast
from ml.metrics import bias, pinball, rmse, rmsse
from ml.quantiles import empirical_quantile

LEVEL_WINDOW = 28
PEER_WINDOW = 112
MIN_PEER_DAYS = 56
TRUE_HISTORY = 112
KEEP_DAYS = (7, 14, 28)
K0_GRID = (7, 14, 28, 56)
LGBM_NAME = "LightGBM (unseen series)"


def peer_groups(series_names) -> np.ndarray:
    """Group label per series: its store and product category, e.g. 'CA_1/FOODS'."""
    labels = []
    for name in series_names:
        store, item = name.split("/")
        labels.append(f"{store}/{item.split('_')[0]}")
    return np.array(labels)


def mean_and_count(block: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Row means and the number of observed days, ignoring days before launch."""
    observed = ~np.isnan(block)
    count = observed.sum(axis=1)
    total = np.where(observed, block, 0.0).sum(axis=1)
    mean = np.divide(total, count, out=np.full(len(count), np.nan), where=count > 0)
    return mean, count


def is_established(
    history: np.ndarray, window: int = PEER_WINDOW, min_days: int = MIN_PEER_DAYS
) -> np.ndarray:
    """True for series with enough recent history to act as a peer."""
    _, count = mean_and_count(history[:, -window:])
    return count >= min_days


def peer_level(history: np.ndarray, groups: np.ndarray, window: int = LEVEL_WINDOW) -> np.ndarray:
    """For each series, the mean recent level of the OTHER established series in its group."""
    levels, _ = mean_and_count(history[:, -window:])
    peers_ok = is_established(history) & ~np.isnan(levels)
    out = np.full(len(groups), np.nan)
    for group in np.unique(groups):
        in_group = groups == group
        peers = in_group & peers_ok
        total, n_peers = levels[peers].sum(), peers.sum()
        for i in np.flatnonzero(in_group):
            is_peer = bool(peers[i])
            n_others = n_peers - is_peer
            if n_others > 0:
                out[i] = (total - (levels[i] if is_peer else 0.0)) / n_others
    return out


def shrunk_level(
    history: np.ndarray, groups: np.ndarray, k0: float, window: int = LEVEL_WINDOW
) -> np.ndarray:
    """Blend each series' own recent average with its peers': w = k / (k + k0)."""
    own, count = mean_and_count(history[:, -window:])
    peer = peer_level(history, groups, window)
    have_own, have_peer = count > 0, ~np.isnan(peer)

    weight = np.divide(count, count + k0, out=np.zeros(len(count)), where=(count + k0) > 0)
    weight = np.where(have_own & have_peer, weight, np.where(have_own, 1.0, 0.0))
    return weight * np.where(have_own, own, 0.0) + (1 - weight) * np.where(have_peer, peer, 0.0)


def cold_start_forecast(
    history: np.ndarray, groups: np.ndarray, horizon: int = HORIZON, k0: float = 28
) -> np.ndarray:
    level = shrunk_level(history, groups, k0)
    return np.tile(level[:, None], (1, horizon))


def peer_ratio_quantile(
    history: np.ndarray, groups: np.ndarray, q: float, window: int = PEER_WINDOW
) -> np.ndarray:
    """Per group, the q-quantile of established peers' daily sales divided by their own mean."""
    recent = history[:, -window:]
    mean, _ = mean_and_count(recent)
    peers_ok = is_established(history) & (mean > 0)
    out = np.full(len(groups), np.nan)
    for group in np.unique(groups):
        in_group = groups == group
        peers = in_group & peers_ok
        if peers.any():
            ratios = recent[peers] / mean[peers, None]
            out[in_group] = np.nanquantile(ratios, q)
    return out


def cold_start_quantile(
    history: np.ndarray,
    groups: np.ndarray,
    horizon: int = HORIZON,
    q: float = 0.9,
    k0: float = 28,
) -> np.ndarray:
    """Peer-shaped q-quantile: the peers' ratio at q, times this series' blended level."""
    level = shrunk_level(history, groups, k0)
    ratio = np.nan_to_num(peer_ratio_quantile(history, groups, q), nan=0.0)
    return np.tile((level * ratio)[:, None], (1, horizon))


def _first_day(values: np.ndarray, origin: int) -> np.ndarray:
    observed = ~np.isnan(values[:, :origin])
    return np.where(observed.any(axis=1), observed.argmax(axis=1) + 1, np.inf)


def choose_series(
    values: np.ndarray,
    origin: int,
    fraction: float = 0.2,
    seed: int = 0,
    min_history: int = TRUE_HISTORY,
) -> np.ndarray:
    """Pick established series (at least `min_history` days) to pretend are new."""
    eligible = np.flatnonzero(_first_day(values, origin) <= origin - min_history)
    size = max(1, round(fraction * len(eligible)))
    rng = np.random.default_rng(seed)
    return np.sort(rng.choice(eligible, size=size, replace=False))


def hide_history(
    values: np.ndarray, prices: np.ndarray, rows: np.ndarray, origin: int, keep_days: int
) -> tuple[np.ndarray, np.ndarray]:
    """Copies where the chosen series look as if they launched `keep_days` before the origin."""
    hidden_values, hidden_prices = values.copy(), prices.copy()
    hidden_values[rows, : origin - keep_days] = np.nan
    hidden_prices[rows, : origin - keep_days] = np.nan
    return hidden_values, hidden_prices


def _model_forecast(model, values, prices, cal, states, rows, origin, horizon) -> np.ndarray:
    """The point model's forecast for the chosen series, in the order of `rows`."""
    grid = forecast(model, values, prices, cal, states, origin, horizon, min_history=1)
    keep = np.flatnonzero(_first_day(values, origin) <= origin - 1)
    position = np.searchsorted(keep, rows)
    if not np.array_equal(keep[position], rows):
        raise ValueError("a simulated series was dropped from the forecast")
    return grid[position]


def simulate(
    values: np.ndarray,
    prices: np.ndarray,
    cal: pd.DataFrame,
    states: list[str],
    groups: np.ndarray,
    origin: int,
    seed: int,
    keep_days: tuple[int, ...] = KEEP_DAYS,
    k0s: tuple[int, ...] = K0_GRID,
    fraction: float = 0.2,
    horizon: int = HORIZON,
    params: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pretend chosen series are new, then score point forecasts and the upper 90% bound."""
    if max(keep_days) > horizon:
        raise ValueError("keep_days must not exceed the horizon, or hidden series leak in")

    rows = choose_series(values, origin, fraction, seed)
    full_history = values[rows, :origin]
    actual = values[rows, origin : origin + horizon]
    if np.isnan(actual).any():
        raise ValueError("actual values contain gaps")

    # With keep_days <= horizon the hidden series produce no training rows at all,
    # so the model has never seen them.
    train_values, train_prices = hide_history(values, prices, rows, origin, max(keep_days))
    table = training_table(train_values, train_prices, cal, states, cutoff=origin, horizon=horizon)
    model = fit(table, weighted=True, params=params)

    point_rows, interval_rows = [], []
    for k in keep_days:
        v, p = hide_history(values, prices, rows, origin, k)
        history = v[:, :origin]
        base = {"origin": origin, "seed": seed, "keep_days": k, "n_series": len(rows)}

        forecasts = {"own history mean": cold_start_forecast(history, groups, horizon, 0)[rows]}
        for k0 in k0s:
            forecasts[f"shrunk k0={k0}"] = cold_start_forecast(history, groups, horizon, k0)[rows]
        forecasts[LGBM_NAME] = _model_forecast(model, v, p, cal, states, rows, origin, horizon)
        for name, predicted in forecasts.items():
            point_rows.append(
                {
                    **base,
                    "method": name,
                    "RMSSE": rmsse(predicted, actual, full_history),
                    "RMSE": rmse(predicted, actual),
                    "bias": bias(predicted, actual),
                }
            )

        uppers = {"own history 90%": empirical_quantile(history[rows], horizon, 0.9, PEER_WINDOW)}
        for k0 in k0s:
            uppers[f"peer shape k0={k0}"] = cold_start_quantile(history, groups, horizon, 0.9, k0)[
                rows
            ]
        for name, upper in uppers.items():
            interval_rows.append(
                {
                    **base,
                    "method": name,
                    "pinball_90": pinball(upper, actual, 0.9),
                    "above_upper": float((actual > upper).mean()),
                    "mean_upper": float(upper.mean()),
                }
            )
    return pd.DataFrame(point_rows), pd.DataFrame(interval_rows)
