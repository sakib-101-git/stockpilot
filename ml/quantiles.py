import numpy as np


def empirical_quantile(history: np.ndarray, horizon: int, q: float, window: int = 56) -> np.ndarray:
    """Each series' own q-quantile of its last `window` days, repeated per horizon day."""
    recent = history[:, -window:]
    level = np.nanquantile(recent, q, axis=1)
    return np.tile(level[:, None], (1, horizon))
