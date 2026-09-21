import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient, Response

from app.api.deps import get_current_user, require_roles
from app.db.models import Role
from app.main import app
from tests.helpers import make_user

NEW_USER = {"email": "new@example.com", "password": "longenough1"}


async def post_users() -> Response:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/users", json=NEW_USER)


async def test_allowed_role_passes() -> None:
    owner = make_user(Role.OWNER)
    checker = require_roles(Role.OWNER)
    assert await checker(current_user=owner) is owner


async def test_other_role_is_forbidden() -> None:
    checker = require_roles(Role.OWNER)
    with pytest.raises(HTTPException) as error:
        await checker(current_user=make_user(Role.STAFF))
    assert error.value.status_code == 403


async def test_several_roles_can_be_allowed() -> None:
    checker = require_roles(Role.OWNER, Role.ADMIN)
    admin = make_user(Role.ADMIN)
    assert await checker(current_user=admin) is admin


async def test_creating_a_user_without_a_token_is_401() -> None:
    response = await post_users()
    assert response.status_code == 401


async def test_staff_cannot_create_users() -> None:
    app.dependency_overrides[get_current_user] = lambda: make_user(Role.STAFF)
    try:
        response = await post_users()
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 403
