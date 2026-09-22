import uuid

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models import Product
from app.services.product_loader import load_products
from tests.helpers import register


def make_products() -> pd.DataFrame:
    return pd.DataFrame({"sku": ["FOODS_1_001", "HOBBIES_1_001"], "cat_id": ["FOODS", "HOBBIES"]})


async def test_load_products_creates_rows_for_the_tenant(client, db_engine: AsyncEngine) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        created = await load_products(session, tenant_id, make_products())

    assert created == 2

    async with maker() as session:
        result = await session.execute(select(Product).where(Product.tenant_id == tenant_id))
        products = {p.sku: p.category for p in result.scalars().all()}
    assert products == {"FOODS_1_001": "FOODS", "HOBBIES_1_001": "HOBBIES"}


async def test_load_products_is_idempotent(client, db_engine: AsyncEngine) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        await load_products(session, tenant_id, make_products())

    async with maker() as session:
        created_again = await load_products(session, tenant_id, make_products())
    assert created_again == 0


async def test_load_products_only_affects_its_own_tenant(client, db_engine: AsyncEngine) -> None:
    user_a = await register(client, "Shop A", "a@example.com")
    user_b = await register(client, "Shop B", "b@example.com")
    tenant_a, tenant_b = uuid.UUID(user_a["tenant_id"]), uuid.UUID(user_b["tenant_id"])

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        await load_products(session, tenant_a, make_products())

    async with maker() as session:
        result_a = await session.execute(select(Product).where(Product.tenant_id == tenant_a))
        result_b = await session.execute(select(Product).where(Product.tenant_id == tenant_b))
    assert len(result_a.scalars().all()) == 2
    assert len(result_b.scalars().all()) == 0
