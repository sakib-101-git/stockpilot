from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.helpers import PASSWORD, db_scalar, login_headers, register


async def test_register_returns_owner_without_password_fields(client: AsyncClient) -> None:
    user = await register(client, "Shop A", "Owner@Example.com")
    assert set(user) == {"id", "tenant_id", "email", "role"}
    assert user["email"] == "owner@example.com"
    assert user["role"] == "owner"


async def test_duplicate_email_is_rejected_and_leaves_no_orphan_tenant(
    client: AsyncClient, db_engine: AsyncEngine
) -> None:
    await register(client, "Shop A", "a@example.com")
    response = await client.post(
        "/auth/register",
        json={"tenant_name": "Shop B", "email": "A@example.com", "password": PASSWORD},
    )
    assert response.status_code == 409
    assert await db_scalar(db_engine, "SELECT count(*) FROM tenants") == 1


async def test_login_is_case_insensitive_and_me_returns_the_user(client: AsyncClient) -> None:
    await register(client, "Shop A", "a@example.com")
    headers = await login_headers(client, "A@Example.com")
    response = await client.get("/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["email"] == "a@example.com"


async def test_wrong_password_and_unknown_email_look_identical(client: AsyncClient) -> None:
    await register(client, "Shop A", "a@example.com")
    wrong = await client.post(
        "/auth/login", data={"username": "a@example.com", "password": "wrong-password-1"}
    )
    unknown = await client.post(
        "/auth/login", data={"username": "nobody@example.com", "password": PASSWORD}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


async def test_disabled_user_loses_access_immediately(
    client: AsyncClient, db_engine: AsyncEngine
) -> None:
    await register(client, "Shop A", "a@example.com")
    headers = await login_headers(client, "a@example.com")
    assert (await client.get("/auth/me", headers=headers)).status_code == 200

    async with db_engine.begin() as conn:
        await conn.execute(text("UPDATE users SET is_active = false"))

    assert (await client.get("/auth/me", headers=headers)).status_code == 401
    response = await client.post(
        "/auth/login", data={"username": "a@example.com", "password": PASSWORD}
    )
    assert response.status_code == 401
