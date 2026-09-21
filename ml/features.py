import numpy as np
import pandas as pd

WINDOWS = (7, 28, 56)
ZERO_WINDOW = 28
SAME_WEEKDAY_WEEKS = 4


def _divide(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    """Divide, returning NaN where the denominator is zero."""
    return np.divide(
        numerator,
        denominator,
        out=np.full(len(denominator), np.nan),
        where=denominator > 0,
    )


def same_weekday_mean(
    values: np.ndarray, origin: int, h: int, weeks: int = SAME_WEEKDAY_WEEKS
) -> np.ndarray:
    """Average sales on the target day's weekday over the last `weeks` such days.

    Only days up to the origin are used.
    """
    day = origin + h
    first = -(-h // 7)
    days = [d for d in (day - 7 * k for k in range(first, first + weeks)) if d >= 1]
    if not days:
        return np.full(values.shape[0], np.nan)
    block = values[:, [d - 1 for d in days]]
    return _divide(np.nansum(block, axis=1), (~np.isnan(block)).sum(axis=1))


def origin_features(values: np.ndarray, origin: int) -> pd.DataFrame:
    """Features known at the end of day `origin`, one row per series.

    Only columns up to `origin` are read, so nothing after it can leak in.
    """
    if not 1 <= origin <= values.shape[1]:
        raise ValueError("origin must be between 1 and the number of days")

    history = values[:, :origin]
    n_days = history.shape[1]
    observed = ~np.isnan(history)

    features: dict[str, np.ndarray] = {"last_day": history[:, -1]}

    for window in WINDOWS:
        recent = history[:, -window:]
        features[f"mean_{window}"] = _divide(
            np.nansum(recent, axis=1), (~np.isnan(recent)).sum(axis=1)
        )

    recent = history[:, -ZERO_WINDOW:]
    features[f"zero_share_{ZERO_WINDOW}"] = _divide(
        (recent == 0).sum(axis=1), (~np.isnan(recent)).sum(axis=1)
    )

    sold = np.nan_to_num(history, nan=0.0) > 0
    features["days_since_sale"] = np.where(
        sold.any(axis=1), np.argmax(sold[:, ::-1], axis=1), n_days
    )

    first_day = np.where(observed.any(axis=1), observed.argmax(axis=1) + 1, np.nan)
    features["history_days"] = n_days - first_day + 1

    changes = np.diff(history, axis=1)
    scale_sq = _divide(np.nansum(changes**2, axis=1), (~np.isnan(changes)).sum(axis=1))
    features["scale_sq"] = np.where(scale_sq > 0, scale_sq, np.nan)
    return pd.DataFrame(features)


FEATURE_COLUMNS = [
    "last_day",
    "mean_7",
    "mean_28",
    "mean_56",
    "zero_share_28",
    "days_since_sale",
    "history_days",
    "h",
    "dow",
    "month",
    "event",
    "snap",
    "price",
    "price_ratio",
    "wd_mean_4",
    "wd_ratio",
]


def calendar_features(calendar: pd.DataFrame) -> pd.DataFrame:
    """Calendar facts for every day number. Known in advance, so safe for any target day."""
    cal = calendar.assign(day=calendar["d"].str[2:].astype(int)).set_index("day").sort_index()
    return pd.DataFrame(
        {
            "dow": cal["date"].dt.dayofweek,
            "month": cal["date"].dt.month,
            "event": cal["event_type_1"].astype("category").cat.codes + 1,
            "snap_CA": cal["snap_CA"],
            "snap_TX": cal["snap_TX"],
            "snap_WI": cal["snap_WI"],
        }
    )


def series_states(series_names) -> list[str]:
    """State code for each series name such as 'CA_1/FOODS_1_046'."""
    return [name.split("/")[0][:2] for name in series_names]


def _last_known(grid: np.ndarray) -> np.ndarray:
    observed = ~np.isnan(grid)
    last_index = grid.shape[1] - 1 - np.argmax(observed[:, ::-1], axis=1)
    return grid[np.arange(grid.shape[0]), last_index]


def build_rows(
    values: np.ndarray,
    prices: np.ndarray,
    cal: pd.DataFrame,
    states: list[str],
    origin: int,
    horizon: int = 28,
) -> pd.DataFrame:
    """One row per series and target day for a single origin."""
    if origin + horizon > values.shape[1]:
        raise ValueError("origin + horizon extends beyond the available days")

    base = origin_features(values, origin)
    base["series_idx"] = np.arange(len(base))
    last_price = _last_known(prices[:, :origin])
    snap_by_state = {state: cal[f"snap_{state}"].to_numpy() for state in set(states)}
    snap = np.stack([snap_by_state[state] for state in states])

    frames = []
    for h in range(1, horizon + 1):
        day = origin + h
        frame = base.copy()
        wd_mean = same_weekday_mean(values, origin, h)
        frame["wd_mean_4"] = wd_mean
        frame["wd_ratio"] = _divide(wd_mean, base["mean_28"].to_numpy())
        frame["origin"] = origin
        frame["target_day"] = day
        frame["h"] = h
        frame["dow"] = cal.at[day, "dow"]
        frame["month"] = cal.at[day, "month"]
        frame["event"] = cal.at[day, "event"]
        frame["snap"] = snap[:, day - 1]
        frame["price"] = prices[:, day - 1]
        frame["price_ratio"] = frame["price"] / last_price
        frame["y"] = values[:, day - 1]
        frames.append(frame)

    rows = pd.concat(frames, ignore_index=True)
    return rows[rows["history_days"].notna() & rows["y"].notna()].reset_index(drop=True)


def training_table(
    values: np.ndarray,
    prices: np.ndarray,
    cal: pd.DataFrame,
    states: list[str],
    cutoff: int,
    horizon: int = 28,
    stride: int = 7,
    first_origin: int = 100,
) -> pd.DataFrame:
    """Training rows whose targets all fall on or before day `cutoff`.

    The arrays are cut at `cutoff` first, so later days cannot be read at all.
    """
    if cutoff > values.shape[1]:
        raise ValueError("cutoff is beyond the available days")

    values, prices = values[:, :cutoff], prices[:, :cutoff]
    origins = range(first_origin, cutoff - horizon + 1, stride)
    if not origins:
        raise ValueError("no training origins fit before the cutoff")

    frames = [build_rows(values, prices, cal, states, origin, horizon) for origin in origins]
    return pd.concat(frames, ignore_index=True)
