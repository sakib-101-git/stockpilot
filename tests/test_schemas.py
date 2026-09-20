import pytest
from pydantic import ValidationError

from app.schemas.auth import RegisterRequest


def test_email_is_lowercased() -> None:
    data = RegisterRequest(tenant_name="Shop", email="Owner@Example.COM", password="longenough1")
    assert data.email == "owner@example.com"


def test_short_password_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(tenant_name="Shop", email="a@example.com", password="short")


def test_invalid_email_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(tenant_name="Shop", email="not-an-email", password="longenough1")


def test_empty_shop_name_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(tenant_name="", email="a@example.com", password="longenough1")
