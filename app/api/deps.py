import uuid
from collections.abc import Awaitable, Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.models import Role, User
from app.db.session import get_session

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        claims = decode_access_token(token)
        user_id = uuid.UUID(claims["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise credentials_error from None

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_error

    await session.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
        {"tenant_id": str(user.tenant_id)},
    )
    return user


def require_roles(*allowed: Role) -> Callable[..., Awaitable[User]]:
    async def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions",
            )
        return current_user

    return checker


require_owner = require_roles(Role.OWNER)
