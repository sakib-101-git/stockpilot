import os
from collections.abc import AsyncIterator
from pathlib import Path

APP_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://stockpilot_app:stockpilot_app@localhost:5433/stockpilot_test",
)
OWNER_URL = os.environ.get(
    "TEST_MIGRATION_DATABASE_URL",
    "postgresql+asyncpg://stockpilot:stockpilot@localhost:5433/stockpilot_test",
)
assert APP_URL.endswith("_test") and OWNER_URL.endswith("_test"), (
    "Refusing to run tests on a non-test database"
)
os.environ["DATABASE_URL"] = APP_URL
os.environ["MIGRATION_DATABASE_URL"] = OWNER_URL

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.db.session import get_session
from app.main import app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def migrated_db() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head")


@pytest.fixture
async def db_engine(migrated_db: None) -> AsyncIterator[AsyncEngine]:
    """Owner connection: sees every row and ignores row-level security."""
    engine = create_async_engine(OWNER_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE tenants, users, products, suppliers, product_suppliers, "
                "stock_movements, batches, import_jobs CASCADE"
            )
        )
    yield engine
    await engine.dispose()


@pytest.fixture
async def app_engine(db_engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    """Application connection: the restricted role, subject to row-level security."""
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def client(app_engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    maker = async_sessionmaker(app_engine, expire_on_commit=False)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()
