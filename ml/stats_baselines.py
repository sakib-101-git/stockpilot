import numpy as np
import pandas as pd
from statsforecast import StatsForecast
from statsforecast.models import TSB, AutoETS, CrostonSBA

BASE_DATE = pd.Timestamp("2011-01-29")


def to_long(history: np.ndarray) -> pd.DataFrame:
    """Turn a (series x days) grid into statsforecast's long format, skipping NaN days."""
    series_idx, day_idx = np.nonzero(~np.isnan(history))
    return pd.DataFrame(
        {
            "unique_id": [f"s{i}" for i in series_idx],
            "ds": BASE_DATE + pd.to_timedelta(day_idx, unit="D"),
            "y": history[series_idx, day_idx],
        }
    )


def make_forecaster(model_factory):
    def forecaster(history: np.ndarray, horizon: int) -> np.ndarray:
        sf = StatsForecast(models=[model_factory()], freq="D")
        fc = sf.forecast(df=to_long(history), h=horizon)
        column = next(c for c in fc.columns if c not in ("unique_id", "ds"))
        grid = fc.pivot(index="unique_id", columns="ds", values=column)
        ids = [f"s{i}" for i in range(history.shape[0])]
        return grid.reindex(ids).to_numpy().clip(min=0)

    return forecaster


STATS_BASELINES = {
    "AutoETS": make_forecaster(lambda: AutoETS(season_length=7)),
    "CrostonSBA": make_forecaster(CrostonSBA),
    "TSB": make_forecaster(lambda: TSB(alpha_d=0.2, alpha_p=0.2)),
}
