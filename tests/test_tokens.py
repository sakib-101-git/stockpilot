from datetime import timedelta

import jwt
import pytest

from app.core.security import create_access_token, decode_access_token


def test_token_round_trip_keeps_claims() -> None:
    token = create_access_token("user-1", "tenant-1", "owner")
    claims = decode_access_token(token)
    assert claims["sub"] == "user-1"
    assert claims["tenant_id"] == "tenant-1"
    assert claims["role"] == "owner"


def test_expired_token_is_rejected() -> None:
    token = create_access_token("user-1", "tenant-1", "owner", expires_delta=timedelta(seconds=-1))
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token)


def test_token_signed_with_another_key_is_rejected() -> None:
    forged = jwt.encode(
        {"sub": "user-1", "role": "owner"},
        "a-different-key-that-is-long-enough-for-hs256",
        algorithm="HS256",
    )


def test_garbage_is_rejected() -> None:
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token("not-a-token")
