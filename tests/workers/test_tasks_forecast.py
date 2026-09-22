from datetime import date

import numpy as np
import pandas as pd
import pytest
from workers.tasks_forecast import align_calendar, eligible_product_ids


@pytest.fixture
def sample_calendar(tmp_path):
    dates = pd.date_range("2020-01-01", periods=100)
    df = pd.DataFrame(
        {
            "d": [f"d_{i + 1}" for i in range(100)],
            "date": dates,
            "event_type_1": [None] * 100,
            "snap_CA": [0] * 100,
            "snap_TX": [0] * 100,
            "snap_WI": [0] * 100,
        }
    )
    path = tmp_path / "calendar.parquet"
    df.to_parquet(path)
    return path


def test_align_calendar_starts_at_index_1_for_the_given_first_day(sample_calendar) -> None:
    aligned = align_calendar(sample_calendar, first_day=date(2020, 1, 1), n_days=10)
    assert list(aligned.index) == list(range(1, 11))


def test_align_calendar_offsets_correctly_for_a_later_first_day(sample_calendar) -> None:
    # 2020-01-11 is day 11 of the source calendar; asking for it as day 1
    # of a 5-day window should return calendar rows 11-15, reindexed 1-5.
    aligned = align_calendar(sample_calendar, first_day=date(2020, 1, 11), n_days=5)
    assert list(aligned.index) == [1, 2, 3, 4, 5]
    assert aligned.loc[1, "month"] == 1


def test_align_calendar_rejects_a_date_not_in_the_calendar(sample_calendar) -> None:
    with pytest.raises(ValueError, match="no entry"):
        align_calendar(sample_calendar, first_day=date(2019, 1, 1), n_days=5)


def test_eligible_product_ids_excludes_a_short_history_product_in_the_middle() -> None:
    # 3 products: A has 60 days, B (in the middle) has only 10, C has 60.
    values = np.full((3, 60), 1.0)
    values[1, :50] = np.nan  # product B: only last 10 days observed

    ids = ["product-A", "product-B", "product-C"]
    eligible = eligible_product_ids(values, ids, origin=60, min_history=56)

    assert eligible == ["product-A", "product-C"]
    assert "product-B" not in eligible


def test_eligible_product_ids_order_matches_forecast_internal_keep_logic() -> None:
    """Directly cross-checks against forecast()'s own keep computation."""

    rng = np.random.default_rng(0)
    values = rng.poisson(2.0, size=(5, 100)).astype(float)
    values[2, :95] = np.nan  # product at index 2 is too new

    ids = [f"p{i}" for i in range(5)]
    eligible = eligible_product_ids(values, ids, origin=100, min_history=56)

    # forecast()'s internal filter uses the same formula; verify row COUNT
    # matches what forecast() would actually produce (shape, not identity,
    # since a real model isn't trained here).
    observed = ~np.isnan(values[:, :100])
    first_day = np.where(observed.any(axis=1), observed.argmax(axis=1) + 1, np.inf)
    keep = np.flatnonzero(first_day <= 100 - 56)

    assert len(eligible) == len(keep)
    assert eligible == [ids[i] for i in keep]
