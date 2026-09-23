import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_owner
from app.db.models import User
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
    return await list_pending_recommendations(session, current_user.tenant_id)


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
