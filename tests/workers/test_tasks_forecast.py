import uuid
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models import Forecast, MovementType, Product, StockMovement
from ml import registry
from tests.helpers import register
from workers.tasks_forecast import align_calendar, generate_forecasts_for_tenant

N_DAYS = 70
N_PRODUCTS = 3
FIRST_ORIGIN = 56
STRIDE = 1


@pytest.fixture(autouse=True)
def isolated_mlflow(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "TRACKING_DB", tmp_path / "mlflow.db")
    monkeypatch.setattr(registry, "_configured", False)


@pytest.fixture
def small_calendar(tmp_path):
    # Extra days beyond N_DAYS so the forecast step's wider calendar lookup
    # (origin + horizon) has real entries to read.
    dates = pd.date_range("2024-01-01", periods=N_DAYS + 40)
    df = pd.DataFrame(
        {
            "d": [f"d_{i + 1}" for i in range(len(dates))],
            "date": dates,
            "event_type_1": [None] * len(dates),
            "snap_CA": [0] * len(dates),
            "snap_TX": [0] * len(dates),
            "snap_WI": [0] * len(dates),
        }
    )
    path = tmp_path / "calendar.parquet"
    df.to_parquet(path)
    return path


async def _seed_tenant_with_history(db_engine: AsyncEngine, client) -> tuple[uuid.UUID, list]:
    user = await register(client, "Test Shop", "forecast-test@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    product_ids = []
    async with maker() as session:
        for i in range(N_PRODUCTS):
            product = Product(
                tenant_id=tenant_id, sku=f"P{i}", name=f"Product {i}", current_price=9.99
            )
            session.add(product)
            await session.flush()
            product_ids.append(product.id)
        await session.commit()

    qty_cycle = [2, 0, 5, 1, 3]
    async with maker() as session:
        for product_id in product_ids:
            for day in range(N_DAYS):
                qty = qty_cycle[day % len(qty_cycle)]
                if qty == 0:
                    continue
                session.add(
                    StockMovement(
                        tenant_id=tenant_id,
                        product_id=product_id,
                        movement_type=MovementType.SALE,
                        quantity=-qty,
                        occurred_at=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=day),
                    )
                )
        await session.commit()

    return tenant_id, product_ids


def test_align_calendar_starts_at_index_1_for_the_given_first_day(small_calendar) -> None:
    aligned = align_calendar(small_calendar, first_day=date(2024, 1, 1), n_days=10)
    assert list(aligned.index) == list(range(1, 11))


def test_align_calendar_offsets_correctly_for_a_later_first_day(small_calendar) -> None:
    aligned = align_calendar(small_calendar, first_day=date(2024, 1, 11), n_days=5)
    assert list(aligned.index) == [1, 2, 3, 4, 5]
    assert aligned.loc[1, "month"] == 1


def test_align_calendar_rejects_a_date_not_in_the_calendar(small_calendar) -> None:
    with pytest.raises(ValueError, match="no entry"):
        align_calendar(small_calendar, first_day=date(2019, 1, 1), n_days=5)


async def test_generate_forecasts_writes_one_row_per_product_per_horizon_day(
    client, db_engine: AsyncEngine, small_calendar
) -> None:
    tenant_id, product_ids = await _seed_tenant_with_history(db_engine, client)

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        written = await generate_forecasts_for_tenant(
            session,
            tenant_id,
            small_calendar,
            horizon=5,
            min_history=56,
            first_origin=FIRST_ORIGIN,
            stride=STRIDE,
        )

    assert written == N_PRODUCTS * 5

    async with maker() as session:
        result = await session.execute(select(Forecast).where(Forecast.tenant_id == tenant_id))
        rows = result.scalars().all()

    assert len(rows) == N_PRODUCTS * 5
    assert {r.product_id for r in rows} == set(product_ids)
    assert all(r.point_estimate is not None and r.point_estimate >= 0 for r in rows)
    assert all(r.upper_bound >= r.point_estimate for r in rows)
    assert all(r.model_version == rows[0].model_version for r in rows)


async def test_generate_forecasts_target_dates_are_consecutive_after_history(
    client, db_engine: AsyncEngine, small_calendar
) -> None:
    tenant_id, _ = await _seed_tenant_with_history(db_engine, client)

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        await generate_forecasts_for_tenant(
            session,
            tenant_id,
            small_calendar,
            horizon=5,
            min_history=56,
            first_origin=FIRST_ORIGIN,
            stride=STRIDE,
        )

    async with maker() as session:
        result = await session.execute(
            select(Forecast.target_date)
            .where(Forecast.tenant_id == tenant_id)
            .distinct()
            .order_by(Forecast.target_date)
        )
        target_dates = [row[0] for row in result.all()]

    assert len(target_dates) == 5
    for i in range(1, len(target_dates)):
        assert (target_dates[i] - target_dates[i - 1]).days == 1
    last_history_date = date(2024, 1, 1) + timedelta(days=N_DAYS - 1)
    assert target_dates[0] == last_history_date + timedelta(days=1)


async def test_generate_forecasts_raises_for_insufficient_history(
    client, db_engine: AsyncEngine, small_calendar
) -> None:
    user = await register(client, "Tiny Shop", "tiny@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        product = Product(tenant_id=tenant_id, sku="P0", name="P0", current_price=1.0)
        session.add(product)
        await session.commit()
        session.add(
            StockMovement(
                tenant_id=tenant_id,
                product_id=product.id,
                movement_type=MovementType.SALE,
                quantity=-1,
                occurred_at=datetime(2024, 1, 1, tzinfo=UTC),
            )
        )
        await session.commit()

    async with maker() as session:
        with pytest.raises(ValueError, match="days of history"):
            await generate_forecasts_for_tenant(
                session,
                tenant_id,
                small_calendar,
                horizon=5,
                min_history=56,
                first_origin=FIRST_ORIGIN,
                stride=STRIDE,
            )


async def test_generate_forecasts_only_writes_for_the_correct_tenant(
    client, db_engine: AsyncEngine, small_calendar
) -> None:
    tenant_a, _ = await _seed_tenant_with_history(db_engine, client)

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        await generate_forecasts_for_tenant(
            session,
            tenant_a,
            small_calendar,
            horizon=3,
            min_history=56,
            first_origin=FIRST_ORIGIN,
            stride=STRIDE,
        )

    user_b = await register(client, "Other Shop", "other@example.com")
    tenant_b = uuid.UUID(user_b["tenant_id"])

    async with maker() as session:
        result_a = await session.execute(select(Forecast).where(Forecast.tenant_id == tenant_a))
        result_b = await session.execute(select(Forecast).where(Forecast.tenant_id == tenant_b))

    assert len(result_a.scalars().all()) > 0
    assert len(result_b.scalars().all()) == 0
