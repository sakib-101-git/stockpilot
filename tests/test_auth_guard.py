import uuid
from datetime import timedelta

import jwt
from httpx import ASGITransport, AsyncClient, Response

from app.core.security import create_access_token
from app.main import app


async def get_me(headers: dict[str, str] | None = None) -> Response:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/auth/me", headers=headers)


async def test_missing_token_is_rejected() -> None:
    response = await get_me()
    assert response.status_code == 401


async def test_garbage_token_is_rejected() -> None:
    response = await get_me({"Authorization": "Bearer not-a-token"})
    assert response.status_code == 401


async def test_expired_token_is_rejected() -> None:
    token = create_access_token(
        str(uuid.uuid4()), str(uuid.uuid4()), "owner", expires_delta=timedelta(seconds=-1)
    )
    response = await get_me({"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_token_signed_with_wrong_key_is_rejected() -> None:
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "role": "owner"},
        "a-different-key-that-is-long-enough-for-hs256",
        algorithm="HS256",
    )
    response = await get_me({"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401
