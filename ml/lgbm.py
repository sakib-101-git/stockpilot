import lightgbm as lgb
import numpy as np
import pandas as pd

from ml.backtest import HORIZON, MIN_HISTORY, split_fold
from ml.features import FEATURE_COLUMNS, build_forecast_rows, build_rows, training_table
from ml.metrics import bias, mae, mase, rmse, rmsse

CATEGORICAL = ["dow", "month", "event"]

DEFAULT_PARAMS = {
    "objective": "regression",
    "n_estimators": 300,
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_child_samples": 100,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "random_state": 42,
    "n_jobs": -1,
    "verbose": -1,
}


def loss_weights(scale_sq: pd.Series, power: float = 1.0) -> np.ndarray:
    """Row weights of 1 / scale_sq**power. Power 1 mirrors RMSSE, 0.5 mirrors pinball loss."""
    weight = scale_sq.to_numpy(dtype=float) ** -power
    finite = np.isfinite(weight)
    if not finite.any():
        return np.ones(len(weight))
    weight[~finite] = np.median(weight[finite])
    return np.minimum(weight, np.quantile(weight, 0.99))


def fit(
    train_table: pd.DataFrame,
    weighted: bool = False,
    params: dict | None = None,
    weight_power: float = 1.0,
) -> lgb.LGBMRegressor:
    model = lgb.LGBMRegressor(**{**DEFAULT_PARAMS, **(params or {})})
    weight = loss_weights(train_table["scale_sq"], weight_power) if weighted else None
    model.fit(
        train_table[FEATURE_COLUMNS],
        train_table["y"],
        sample_weight=weight,
        categorical_feature=CATEGORICAL,
    )
    return model


def forecast(
    model: lgb.LGBMRegressor,
    values: np.ndarray,
    prices: np.ndarray,
    cal: pd.DataFrame,
    states: list[str],
    origin: int,
    horizon: int = HORIZON,
    min_history: int = MIN_HISTORY,
) -> np.ndarray:
    """Forecast grid for one fold, with rows in the same order `split_fold` returns."""
    observed = ~np.isnan(values[:, :origin])
    first_day = np.where(observed.any(axis=1), observed.argmax(axis=1) + 1, np.inf)
    keep = np.flatnonzero(first_day <= origin - min_history)

    rows = build_rows(values, prices, cal, states, origin=origin, horizon=horizon)
    rows = rows[rows["series_idx"].isin(keep)]
    predicted = np.clip(model.predict(rows[FEATURE_COLUMNS]), 0, None)

    grid = pd.DataFrame(
        {"series_idx": rows["series_idx"].to_numpy(), "h": rows["h"].to_numpy(), "p": predicted}
    ).pivot(index="series_idx", columns="h", values="p")
    return grid.loc[keep].to_numpy()


def backtest(
    values: np.ndarray,
    prices: np.ndarray,
    cal: pd.DataFrame,
    states: list[str],
    origins: tuple[int, ...],
    weighted: bool = False,
    params: dict | None = None,
    name: str = "LightGBM",
    horizon: int = HORIZON,
    min_history: int = MIN_HISTORY,
) -> pd.DataFrame:
    """Train one model per origin, using only targets up to that origin, and score it."""
    results = []
    for origin in origins:
        table = training_table(values, prices, cal, states, cutoff=origin, horizon=horizon)
        model = fit(table, weighted, params)
        history, actual = split_fold(values, origin, horizon, min_history)
        predicted = forecast(model, values, prices, cal, states, origin, horizon, min_history)
        if predicted.shape != actual.shape:
            raise ValueError(f"forecast shape {predicted.shape} != actual shape {actual.shape}")
        results.append(
            {
                "origin": origin,
                "method": name,
                "n_series": history.shape[0],
                "MAE": mae(predicted, actual),
                "RMSE": rmse(predicted, actual),
                "bias": bias(predicted, actual),
                "MASE": mase(predicted, actual, history),
                "RMSSE": rmsse(predicted, actual, history),
            }
        )
    return pd.DataFrame(results)


def forecast_future(
    model: lgb.LGBMRegressor,
    values: np.ndarray,
    prices: np.ndarray,
    cal: pd.DataFrame,
    states: list[str],
    origin: int,
    horizon: int = HORIZON,
    min_history: int = MIN_HISTORY,
) -> tuple[np.ndarray, list[int]]:
    """Forecast horizon days beyond `origin`, for days with no ground truth yet.

    Unlike forecast(), does not require values/prices to extend past origin.
    Returns the forecast grid and the row indices (into values/prices) that
    were eligible and forecast, in the same order as the grid's rows.
    """
    observed = ~np.isnan(values[:, :origin])
    first_day = np.where(observed.any(axis=1), observed.argmax(axis=1) + 1, np.inf)
    keep = np.flatnonzero(first_day <= origin - min_history)

    rows = build_forecast_rows(values, prices, cal, states, origin=origin, horizon=horizon)
    rows = rows[rows["series_idx"].isin(keep)]
    predicted = np.clip(model.predict(rows[FEATURE_COLUMNS]), 0, None)

    grid = pd.DataFrame(
        {"series_idx": rows["series_idx"].to_numpy(), "h": rows["h"].to_numpy(), "p": predicted}
    ).pivot(index="series_idx", columns="h", values="p")
    return grid.loc[keep].to_numpy(), list(keep)
