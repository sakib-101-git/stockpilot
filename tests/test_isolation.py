import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.helpers import PASSWORD, db_scalar, login_headers, register

PRODUCT = {"sku": "SKU-1", "name": "Bread"}
SUPPLIER = {"name": "Fresh Foods Ltd"}


@pytest.fixture
async def shops(client: AsyncClient) -> dict[str, dict[str, str]]:
    await register(client, "Shop A", "a@example.com")
    await register(client, "Shop B", "b@example.com")
    return {
        "a": await login_headers(client, "a@example.com"),
        "b": await login_headers(client, "b@example.com"),
    }


async def test_product_lists_are_separate(client: AsyncClient, shops: dict) -> None:
    await client.post("/products", json=PRODUCT, headers=shops["a"])
    a = await client.get("/products", headers=shops["a"])
    b = await client.get("/products", headers=shops["b"])
    assert [p["sku"] for p in a.json()] == ["SKU-1"]
    assert b.json() == []


async def test_other_shops_product_looks_like_it_does_not_exist(
    client: AsyncClient, shops: dict
) -> None:
    created = await client.post("/products", json=PRODUCT, headers=shops["a"])
    product_id = created.json()["id"]

    own = await client.get(f"/products/{product_id}", headers=shops["a"])
    other = await client.get(f"/products/{product_id}", headers=shops["b"])
    missing = await client.get(f"/products/{uuid.uuid4()}", headers=shops["b"])

    assert own.status_code == 200
    assert other.status_code == 404
    assert other.json() == missing.json()


async def test_same_sku_is_allowed_in_two_shops_but_not_twice_in_one(
    client: AsyncClient, shops: dict
) -> None:
    assert (await client.post("/products", json=PRODUCT, headers=shops["a"])).status_code == 201
    assert (await client.post("/products", json=PRODUCT, headers=shops["b"])).status_code == 201
    assert (await client.post("/products", json=PRODUCT, headers=shops["a"])).status_code == 409


async def test_tenant_id_in_the_request_body_is_ignored(client: AsyncClient, shops: dict) -> None:
    shop_b = (await client.get("/auth/me", headers=shops["b"])).json()["tenant_id"]
    body = {**PRODUCT, "tenant_id": shop_b}

    created = await client.post("/products", json=body, headers=shops["a"])

    assert created.status_code == 201
    assert (await client.get("/products", headers=shops["b"])).json() == []


async def test_created_rows_are_stored_with_the_owners_tenant(
    client: AsyncClient, shops: dict, db_engine: AsyncEngine
) -> None:
    await client.post("/products", json=PRODUCT, headers=shops["a"])
    sql = (
        "SELECT count(*) FROM products p JOIN users u ON u.tenant_id = p.tenant_id "
        "WHERE u.email = '{}'"
    )
    assert await db_scalar(db_engine, sql.format("a@example.com")) == 1
    assert await db_scalar(db_engine, sql.format("b@example.com")) == 0


async def test_supplier_lists_are_separate(client: AsyncClient, shops: dict) -> None:
    await client.post("/suppliers", json=SUPPLIER, headers=shops["a"])
    a = await client.get("/suppliers", headers=shops["a"])
    b = await client.get("/suppliers", headers=shops["b"])
    assert [s["name"] for s in a.json()] == ["Fresh Foods Ltd"]
    assert b.json() == []


async def test_other_shops_supplier_looks_like_it_does_not_exist(
    client: AsyncClient, shops: dict
) -> None:
    created = await client.post("/suppliers", json=SUPPLIER, headers=shops["a"])
    supplier_id = created.json()["id"]

    other = await client.get(f"/suppliers/{supplier_id}", headers=shops["b"])
    missing = await client.get(f"/suppliers/{uuid.uuid4()}", headers=shops["b"])

    assert other.status_code == 404
    assert other.json() == missing.json()


async def test_same_supplier_name_is_allowed_in_two_shops(client: AsyncClient, shops: dict) -> None:
    assert (await client.post("/suppliers", json=SUPPLIER, headers=shops["a"])).status_code == 201
    assert (await client.post("/suppliers", json=SUPPLIER, headers=shops["b"])).status_code == 201


async def test_user_lists_are_separate(client: AsyncClient, shops: dict) -> None:
    staff = {"email": "staff@example.com", "password": PASSWORD}
    await client.post("/users", json=staff, headers=shops["a"])

    a = await client.get("/users", headers=shops["a"])
    b = await client.get("/users", headers=shops["b"])

    assert {u["email"] for u in a.json()} == {"a@example.com", "staff@example.com"}
    assert {u["email"] for u in b.json()} == {"b@example.com"}
