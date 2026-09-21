from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import settings


def test_suite_runs_against_the_test_database() -> None:
    assert settings.database_url.endswith("_test")


async def test_migrations_created_the_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as conn:
        result = await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        names = {row[0] for row in result}
    assert {"tenants", "users", "products", "suppliers"} <= names


async def test_readiness_endpoint_with_real_services(client: AsyncClient) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200