from app.core.security import hash_password, verify_password


def test_hash_is_not_the_plain_password() -> None:
    assert hash_password("secret123") != "secret123"


def test_same_password_gives_different_hashes() -> None:
    assert hash_password("secret123") != hash_password("secret123")


def test_correct_password_verifies() -> None:
    hashed = hash_password("secret123")
    assert verify_password("secret123", hashed) is True


def test_wrong_password_is_rejected() -> None:
    hashed = hash_password("secret123")
    assert verify_password("not-the-password", hashed) is False
