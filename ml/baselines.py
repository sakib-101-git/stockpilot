import numpy as np


def zero(history: np.ndarray, horizon: int) -> np.ndarray:
    return np.zeros((history.shape[0], horizon))


def naive(history: np.ndarray, horizon: int) -> np.ndarray:
    return np.tile(history[:, -1:], (1, horizon))


def seasonal_naive(history: np.ndarray, horizon: int, season: int = 7) -> np.ndarray:
    last_season = history[:, -season:]
    repeats = int(np.ceil(horizon / season))
    return np.tile(last_season, (1, repeats))[:, :horizon]


def moving_average(history: np.ndarray, horizon: int, window: int = 28) -> np.ndarray:
    level = np.nanmean(history[:, -window:], axis=1)
    return np.tile(level[:, None], (1, horizon))


BASELINES = {
    "zero": zero,
    "naive": naive,
    "seasonal naive": seasonal_naive,
    "moving avg 28d": moving_average,
}
