import numpy as np


def mae(forecast: np.ndarray, actual: np.ndarray) -> float:
    return float(np.abs(forecast - actual).mean())


def rmse(forecast: np.ndarray, actual: np.ndarray) -> float:
    return float(np.sqrt(((forecast - actual) ** 2).mean()))


def bias(forecast: np.ndarray, actual: np.ndarray) -> float:
    return float((forecast - actual).mean())


def one_step_scale(history: np.ndarray, squared: bool = False) -> np.ndarray:
    changes = np.diff(history, axis=1)
    changes = changes**2 if squared else np.abs(changes)
    scale = np.nanmean(changes, axis=1)
    return np.where(scale > 0, scale, np.nan)


def mase(forecast: np.ndarray, actual: np.ndarray, history: np.ndarray) -> float:
    per_series = np.abs(forecast - actual).mean(axis=1) / one_step_scale(history)
    return float(np.nanmean(per_series))


def rmsse(forecast: np.ndarray, actual: np.ndarray, history: np.ndarray) -> float:
    mse = ((forecast - actual) ** 2).mean(axis=1)
    return float(np.nanmean(np.sqrt(mse / one_step_scale(history, squared=True))))


def pinball(forecast: np.ndarray, actual: np.ndarray, q: float) -> float:
    """Average pinball loss for the q-quantile. Lower is better."""
    diff = actual - forecast
    return float(np.mean(np.maximum(q * diff, (q - 1) * diff)))


def coverage(lower: np.ndarray, upper: np.ndarray, actual: np.ndarray) -> float:
    """Share of actual values inside [lower, upper], ends included."""
    return float(np.mean((actual >= lower) & (actual <= upper)))


def mean_width(lower: np.ndarray, upper: np.ndarray) -> float:
    return float(np.mean(upper - lower))
