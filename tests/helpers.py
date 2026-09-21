import uuid

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import Role, User


def make_user(role: Role) -> User:
    return User(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        email="someone@example.com",
        hashed_password="not-a-real-hash",
        role=role,
        is_active=True,
    )

PASSWORD = "correct-horse-9"


async def register(client: AsyncClient, tenant_name: str, email: str) -> dict:
    response = await client.post(
        "/auth/register",
        json={"tenant_name": tenant_name, "email": email, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def login_headers(client: AsyncClient, email: str) -> dict[str, str]:
    response = await client.post("/auth/login", data={"username": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def db_scalar(engine: AsyncEngine, sql: str) -> object:
    async with engine.connect() as conn:
        return (await conn.execute(text(sql))).scalar_one()