"""Tests for the AI assistant's tenant isolation and grounding.

Uses real, seeded test data (not hardcoded dev-database UUIDs) — an
earlier version of these tests hardcoded CA_1's real product/tenant IDs
from the dev database, which silently always failed under pytest because
tests/conftest.py points DATABASE_URL at the separate, empty
stockpilot_test database. That looked exactly like LLM non-determinism at
first and cost real time to trace back to the actual cause. These tests
seed their own forecast data instead.

Calls Assistant.ask() for real, making real Gemini API calls — slower and
dependent on external network/API availability, unlike the rest of this
project's test suite. Skipped automatically if no GEMINI_API_KEY is
configured.
"""

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import settings
from app.db.models import Forecast, Product
from app.services.assistant import Assistant
from tests.helpers import register

pytestmark = pytest.mark.skipif(not settings.gemini_api_key, reason="GEMINI_API_KEY not configured")


async def _seed_product_with_forecast(
    db_engine: AsyncEngine, tenant_id: uuid.UUID, sku: str = "A1"
) -> uuid.UUID:
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        product = Product(tenant_id=tenant_id, sku=sku, name=sku, current_price=5.0)
        session.add(product)
        await session.flush()
        product_id = product.id
        session.add(
            Forecast(
                tenant_id=tenant_id,
                product_id=product_id,
                target_date=date(2024, 1, 1),
                point_estimate=42.5,
                upper_bound=60.0,
                model_version=1,
                generated_at=datetime.now(UTC),
            )
        )
        await session.commit()
    return product_id


async def test_get_forecast_tool_directly_returns_real_data(client, db_engine) -> None:
    """Bypasses the LLM entirely — proves the tool and database layer are
    correct regardless of the LLM's tool-calling reliability.
    """
    user = await register(client, "Shop A", "assistant-a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    product_id = await _seed_product_with_forecast(db_engine, tenant_id)

    assistant = Assistant(tenant_id)
    result = assistant._get_forecast(str(product_id))
    assert "point=42.5" in result


async def test_assistant_cannot_see_another_tenants_forecast(client, db_engine) -> None:
    user_a = await register(client, "Shop A", "assistant-b@example.com")
    tenant_a = uuid.UUID(user_a["tenant_id"])
    product_id = await _seed_product_with_forecast(db_engine, tenant_a)

    user_b = await register(client, "Shop B", "assistant-c@example.com")
    tenant_b = uuid.UUID(user_b["tenant_id"])

    assistant = Assistant(tenant_b)
    answer = assistant.ask(f"What is the forecast for product {product_id}?")
    assert "42.5" not in answer


async def test_assistant_sees_its_own_tenants_forecast(client, db_engine) -> None:
    user = await register(client, "Shop A", "assistant-d@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    product_id = await _seed_product_with_forecast(db_engine, tenant_id)

    for _ in range(2):
        assistant = Assistant(tenant_id)
        answer = assistant.ask(f"What is the forecast for product {product_id}?")
        if "42.5" in answer:
            return
    pytest.fail("assistant did not return real forecast data in 2 attempts")
