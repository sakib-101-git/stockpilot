from collections.abc import Callable

import numpy as np
import pandas as pd

from ml.metrics import bias, mae, mase, rmse, rmsse

Forecaster = Callable[[np.ndarray, int], np.ndarray]

HORIZON = 28
MIN_HISTORY = 56
FOLDS = (1421, 1785, 1829, 1857, 1885, 1913)
N_DAYS = 1941


def make_grid(sales: pd.DataFrame, n_days: int = N_DAYS) -> pd.DataFrame:
    """One row per series, one column per day number. Days before launch are NaN."""
    prepared = sales.assign(
        series=sales["store_id"] + "/" + sales["item_id"],
        day=sales["d"].str[2:].astype(int),
    )
    grid = prepared.pivot(index="series", columns="day", values="units")
    return grid.reindex(columns=range(1, n_days + 1))


def split_fold(
    values: np.ndarray,
    origin: int,
    horizon: int = HORIZON,
    min_history: int = MIN_HISTORY,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (history, actual) for one fold. History ends at the origin day."""
    if origin + horizon > values.shape[1]:
        raise ValueError("fold extends beyond the available days")

    history = values[:, :origin]
    actual = values[:, origin : origin + horizon]

    observed = ~np.isnan(history)
    first_day = np.where(observed.any(axis=1), observed.argmax(axis=1) + 1, np.inf)
    eligible = first_day <= origin - min_history

    history, actual = history[eligible], actual[eligible]
    if np.isnan(actual).any():
        raise ValueError("actual values contain gaps")

    history.flags.writeable = False
    return history, actual


def run_backtest(
    grid: pd.DataFrame,
    forecasters: dict[str, Forecaster],
    folds: tuple[int, ...] = FOLDS,
    horizon: int = HORIZON,
    min_history: int = MIN_HISTORY,
) -> pd.DataFrame:
    values = grid.to_numpy(dtype=float)
    rows = []
    for origin in folds:
        history, actual = split_fold(values, origin, horizon, min_history)
        for name, forecaster in forecasters.items():
            forecast = forecaster(history, horizon)
            if forecast.shape != actual.shape:
                raise ValueError(f"{name}: forecast shape {forecast.shape} != {actual.shape}")
            rows.append(
                {
                    "origin": origin,
                    "method": name,
                    "n_series": history.shape[0],
                    "MAE": mae(forecast, actual),
                    "RMSE": rmse(forecast, actual),
                    "bias": bias(forecast, actual),
                    "MASE": mase(forecast, actual, history),
                    "RMSSE": rmsse(forecast, actual, history),
                }
            )
    return pd.DataFrame(rows)


def summarize(results: pd.DataFrame, metric: str) -> pd.DataFrame:
    table = results.pivot(index="method", columns="origin", values=metric)
    table["mean"] = table.mean(axis=1)
    return table.round(3)
