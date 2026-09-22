"""Thin wrapper around MLflow's tracking and model registry.

Uses aliases (not the deprecated "stages" concept) to mark which registered
model version is currently in production use — see docs/decisions for why,
confirmed against the actual installed MLflow version (3.16.1) in Week 8's
exploratory notebook work.
"""

from pathlib import Path

import mlflow
import mlflow.lightgbm
from mlflow import MlflowClient

MODEL_NAME = "stockpilot-point-forecast"
CHAMPION_ALIAS = "champion"
ROOT = Path(__file__).resolve().parents[1]
TRACKING_DB = ROOT / "mlflow.db"

_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return
    mlflow.set_tracking_uri(f"sqlite:///{TRACKING_DB}")
    mlflow.set_experiment("stockpilot-forecast")
    _configured = True


def log_and_register(model, params: dict, metrics: dict, run_name: str) -> int:
    """Log a training run and register the model as a new version. Returns the version number."""
    _configure()
    with mlflow.start_run(run_name=run_name) as run:
        for key, value in params.items():
            mlflow.log_param(key, value)
        for key, value in metrics.items():
            mlflow.log_metric(key, value)
        mlflow.lightgbm.log_model(model, artifact_path="model", registered_model_name=MODEL_NAME)
        run_id = run.info.run_id

    client = MlflowClient()
    versions = client.search_model_versions(f"run_id='{run_id}'")
    if not versions:
        raise RuntimeError(f"model was logged but no version found for run {run_id}")
    return int(versions[0].version)


def promote_to_champion(version: int) -> None:
    """Mark a registered model version as the one the nightly job should use."""
    _configure()
    client = MlflowClient()
    client.set_registered_model_alias(MODEL_NAME, CHAMPION_ALIAS, version)


def load_champion():
    """Load whatever model version currently holds the champion alias."""
    _configure()
    return mlflow.lightgbm.load_model(f"models:/{MODEL_NAME}@{CHAMPION_ALIAS}")


def champion_version() -> int:
    """The version number currently aliased as champion, for recording on Forecast rows."""
    _configure()
    client = MlflowClient()
    mv = client.get_model_version_by_alias(MODEL_NAME, CHAMPION_ALIAS)
    return int(mv.version)
