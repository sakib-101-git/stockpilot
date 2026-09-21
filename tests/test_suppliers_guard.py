import pytest
from httpx import ASGITransport, AsyncClient, Response
from pydantic import ValidationError

from app.api.deps import get_current_user
from app.db.models import Role
from app.main import app
from app.schemas.supplier import SupplierCreate
from tests.helpers import make_user

NEW_SUPPLIER = {"name": "Fresh Foods Ltd"}


async def call(method: str, url: str, json: dict | None = None) -> Response:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, url, json=json)


async def test_listing_suppliers_without_token_is_401() -> None:
    assert (await call("GET", "/suppliers")).status_code == 401


async def test_creating_supplier_without_token_is_401() -> None:
    assert (await call("POST", "/suppliers", NEW_SUPPLIER)).status_code == 401


async def test_staff_cannot_create_suppliers() -> None:
    app.dependency_overrides[get_current_user] = lambda: make_user(Role.STAFF)
    try:
        response = await call("POST", "/suppliers", NEW_SUPPLIER)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 403


def test_empty_supplier_name_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SupplierCreate(name="")


def test_invalid_contact_email_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SupplierCreate(name="Fresh Foods Ltd", contact_email="not-an-email")
