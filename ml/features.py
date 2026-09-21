import numpy as np
import pandas as pd

WINDOWS = (7, 28, 56)
ZERO_WINDOW = 28


def _divide(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    """Divide, returning NaN where the denominator is zero."""
    return np.divide(
        numerator,
        denominator,
        out=np.full(len(denominator), np.nan),
        where=denominator > 0,
    )


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

    return pd.DataFrame(features)
