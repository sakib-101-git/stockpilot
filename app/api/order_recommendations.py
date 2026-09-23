import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_owner
from app.db.models import Product, User
from app.db.session import get_session
from app.schemas.order_recommendation import (
    EditRecommendationRequest,
    GenerateRecommendationsRequest,
    OrderRecommendationOut,
)
from app.services.order_recommendations import (
    approve_recommendation,
    edit_recommendation,
    generate_recommendations,
    list_pending_recommendations,
    reject_recommendation,
)

router = APIRouter(tags=["order-recommendations"])


def _status_for(exc: ValueError) -> int:
    return 409 if "already" in str(exc) else 404


@router.post("/recommendations/generate", response_model=list[OrderRecommendationOut])
async def create_recommendations(
    body: GenerateRecommendationsRequest,
    current_user: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
):
    return await generate_recommendations(session, current_user.tenant_id, body.budget)


@router.get("/recommendations/pending", response_model=list[OrderRecommendationOut])
async def get_pending_recommendations(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    rows = await list_pending_recommendations(session, current_user.tenant_id)
    product_ids = [row.product_id for row in rows]
    skus: dict[uuid.UUID, str] = {}
    if product_ids:
        result = await session.execute(select(Product).where(Product.id.in_(product_ids)))
        skus = {p.id: p.sku for p in result.scalars().all()}

    return [
        OrderRecommendationOut(
            id=row.id,
            product_id=row.product_id,
            sku=skus.get(row.product_id),
            suggested_quantity=row.suggested_quantity,
            suggested_cost=float(row.suggested_cost),
            status=row.status,
            final_quantity=row.final_quantity,
            decided_by=row.decided_by,
            decided_at=row.decided_at,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("/recommendations/{recommendation_id}/approve", response_model=OrderRecommendationOut)
async def approve(
    recommendation_id: uuid.UUID,
    current_user: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await approve_recommendation(
            session, current_user.tenant_id, recommendation_id, current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=_status_for(exc), detail=str(exc)) from None


@router.post("/recommendations/{recommendation_id}/edit", response_model=OrderRecommendationOut)
async def edit(
    recommendation_id: uuid.UUID,
    body: EditRecommendationRequest,
    current_user: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await edit_recommendation(
            session, current_user.tenant_id, recommendation_id, current_user.id, body.new_quantity
        )
    except ValueError as exc:
        raise HTTPException(status_code=_status_for(exc), detail=str(exc)) from None


@router.post("/recommendations/{recommendation_id}/reject", response_model=OrderRecommendationOut)
async def reject(
    recommendation_id: uuid.UUID,
    current_user: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await reject_recommendation(
            session, current_user.tenant_id, recommendation_id, current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=_status_for(exc), detail=str(exc)) from None
