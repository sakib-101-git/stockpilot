import uuid

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
