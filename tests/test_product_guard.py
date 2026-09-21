import pytest
from httpx import ASGITransport, AsyncClient, Response
from pydantic import ValidationError

from app.api.deps import get_current_user
from app.db.models import Role
from app.main import app
from app.schemas.product import ProductCreate
from tests.helpers import make_user

NEW_PRODUCT = {"sku": "FOODS_1_046", "name": "Bread"}


async def call(method: str, url: str, json: dict | None = None) -> Response:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, url, json=json)


async def test_listing_products_without_token_is_401() -> None:
    assert (await call("GET", "/products")).status_code == 401


async def test_creating_product_without_token_is_401() -> None:
    assert (await call("POST", "/products", NEW_PRODUCT)).status_code == 401


async def test_staff_cannot_create_products() -> None:
    app.dependency_overrides[get_current_user] = lambda: make_user(Role.STAFF)
    try:
        response = await call("POST", "/products", NEW_PRODUCT)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 403


def test_empty_sku_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ProductCreate(sku="", name="Bread")


def test_too_long_sku_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ProductCreate(sku="x" * 65, name="Bread")
