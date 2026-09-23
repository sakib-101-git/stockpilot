import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import Product, User
from app.db.session import get_session
from app.schemas.reorder import OptimizationResultOut, ReorderRecommendationOut
from app.services.optimizer import optimize_budget
from app.services.reorder import get_reorder_recommendation

router = APIRouter(tags=["reorder"])


@router.get("/products/{product_id}/reorder", response_model=ReorderRecommendationOut)
async def get_product_reorder(
    product_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    product = await session.get(Product, product_id)
    if product is None or product.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Product not found")

    try:
        return await get_reorder_recommendation(session, product_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/optimize-budget", response_model=OptimizationResultOut)
async def get_optimized_orders(
    budget: float = Query(..., gt=0, description="Purchasing budget for this round"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await optimize_budget(session, current_user.tenant_id, budget)
