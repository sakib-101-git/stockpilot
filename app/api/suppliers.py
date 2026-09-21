import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_owner
from app.db.models import Supplier, User
from app.db.session import get_session
from app.schemas.supplier import SupplierCreate, SupplierRead

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.post("", response_model=SupplierRead, status_code=status.HTTP_201_CREATED)
async def create_supplier(
    data: SupplierCreate,
    current_user: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> Supplier:
    supplier = Supplier(tenant_id=current_user.tenant_id, **data.model_dump())
    session.add(supplier)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Supplier name already exists") from None

    return supplier


@router.get("", response_model=list[SupplierRead])
async def list_suppliers(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Supplier]:
    result = await session.execute(
        select(Supplier)
        .where(Supplier.tenant_id == current_user.tenant_id)
        .order_by(Supplier.name)
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


@router.get("/{supplier_id}", response_model=SupplierRead)
async def get_supplier(
    supplier_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Supplier:
    result = await session.execute(
        select(Supplier).where(
            Supplier.id == supplier_id,
            Supplier.tenant_id == current_user.tenant_id,
        )
    )
    supplier = result.scalar_one_or_none()
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return supplier
