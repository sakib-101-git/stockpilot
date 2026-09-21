from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import Role, Tenant, User
from app.db.session import get_session
from app.schemas.auth import RegisterRequest, Token, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])
DUMMY_HASH = hash_password("not-a-real-password")


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(
    data: RegisterRequest,
    session: AsyncSession = Depends(get_session),
) -> User:
    tenant = Tenant(name=data.tenant_name)
    session.add(tenant)
    await session.flush()

    user = User(
        tenant_id=tenant.id,
        email=data.email,
        hashed_password=hash_password(data.password),
        role=Role.OWNER,
    )
    session.add(user)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Email already registered") from None

    return user


@router.post("/login", response_model=Token)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session),
) -> Token:
    email = form.username.lower()
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    hashed = user.hashed_password if user else DUMMY_HASH
    password_ok = verify_password(form.password, hashed)

    if user is None or not password_ok or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(str(user.id), str(user.tenant_id), user.role)
    return Token(access_token=token)
