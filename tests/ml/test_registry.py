from pathlib import Path

import lightgbm as lgb
import numpy as np
import pytest

from ml import registry


@pytest.fixture(autouse=True)
def isolated_tracking_db(tmp_path: Path, monkeypatch):
    """Point the registry at a throwaway MLflow DB for each test."""
    monkeypatch.setattr(registry, "TRACKING_DB", tmp_path / "mlflow.db")
    monkeypatch.setattr(registry, "_configured", False)
    yield


def make_model():
    rng = np.random.default_rng(0)
    x = rng.random((50, 3))
    y = rng.random(50)
    return lgb.LGBMRegressor(n_estimators=5, verbose=-1).fit(x, y)


def test_log_and_register_returns_a_version_number() -> None:
    version = registry.log_and_register(
        make_model(), params={"origin": 1913}, metrics={"rmsse": 0.7}, run_name="test-run"
    )
    assert version == 1


def test_second_registration_gets_the_next_version_number() -> None:
    registry.log_and_register(make_model(), {}, {}, "run-1")
    version_2 = registry.log_and_register(make_model(), {}, {}, "run-2")
    assert version_2 == 2


def test_promote_and_load_champion_round_trips() -> None:
    model = make_model()
    version = registry.log_and_register(model, {}, {}, "run-1")
    registry.promote_to_champion(version)

    loaded = registry.load_champion()
    sample = np.random.default_rng(1).random((10, 3))
    np.testing.assert_array_equal(model.predict(sample), loaded.predict(sample))


def test_champion_version_reflects_the_alias() -> None:
    registry.log_and_register(make_model(), {}, {}, "run-1")
    v2 = registry.log_and_register(make_model(), {}, {}, "run-2")
    registry.promote_to_champion(v2)

    assert registry.champion_version() == v2


def test_promoting_a_different_version_moves_the_alias() -> None:
    v1 = registry.log_and_register(make_model(), {}, {}, "run-1")
    v2 = registry.log_and_register(make_model(), {}, {}, "run-2")

    registry.promote_to_champion(v1)
    assert registry.champion_version() == v1

    registry.promote_to_champion(v2)
    assert registry.champion_version() == v2
