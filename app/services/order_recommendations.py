"""Persisting optimizer output as recommendations, and the approve/edit/
reject decisions a user makes on them.

Every function sets app.current_tenant itself, rather than trusting that
a caller's earlier setting is still active — set_config(..., true) is
transaction-local and clears on commit, so a function that runs after an
earlier commit in the same session cannot rely on a previous caller's
setting. This was found by chaining generate_recommendations (which
commits) directly into approve_recommendation in the same session, which
failed with a StaleDataError until each function set its own context.

A recommendation can only transition out of PENDING once. Attempting to
act on a non-pending recommendation raises ValueError rather than
silently overwriting a prior decision.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OrderRecommendation, RecommendationStatus
from app.services.optimizer import optimize_budget


async def _set_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


async def generate_recommendations(
    session: AsyncSession, tenant_id: uuid.UUID, budget: float
) -> list[OrderRecommendation]:
    """Runs the optimizer and persists each chosen order as a pending
    recommendation.

    Any existing pending recommendation for a product in this new batch is
    marked superseded first, so re-running generate does not silently pile
    up stale suggestions alongside fresh ones for the same product.
    Superseded is distinct from rejected: rejected means a person decided
    against the order; superseded means a newer run replaced it before
    anyone acted.
    """
    await _set_tenant(session, tenant_id)
    result = await optimize_budget(session, tenant_id, budget)

    product_ids = [order.product_id for order in result.orders]
    if product_ids:
        stale = await session.execute(
            select(OrderRecommendation).where(
                OrderRecommendation.tenant_id == tenant_id,
                OrderRecommendation.product_id.in_(product_ids),
                OrderRecommendation.status == RecommendationStatus.PENDING,
            )
        )
        for old_row in stale.scalars().all():
            old_row.status = RecommendationStatus.SUPERSEDED

    rows = []
    for order in result.orders:
        row = OrderRecommendation(
            tenant_id=tenant_id,
            product_id=order.product_id,
            suggested_quantity=order.order_quantity,
            suggested_cost=order.cost,
            status=RecommendationStatus.PENDING,
        )
        session.add(row)
        rows.append(row)
    await session.commit()
    return rows


async def _get_pending(
    session: AsyncSession, tenant_id: uuid.UUID, recommendation_id: uuid.UUID
) -> OrderRecommendation:
    await _set_tenant(session, tenant_id)
    row = await session.get(OrderRecommendation, recommendation_id)
    if row is None or row.tenant_id != tenant_id:
        raise ValueError(f"recommendation {recommendation_id} not found")
    if row.status != RecommendationStatus.PENDING:
        raise ValueError(
            f"recommendation {recommendation_id} is already {row.status}, cannot act on it again"
        )
    return row


async def approve_recommendation(
    session: AsyncSession, tenant_id: uuid.UUID, recommendation_id: uuid.UUID, user_id: uuid.UUID
) -> OrderRecommendation:
    row = await _get_pending(session, tenant_id, recommendation_id)
    row.status = RecommendationStatus.APPROVED
    row.final_quantity = row.suggested_quantity
    row.decided_by = user_id
    row.decided_at = datetime.now(UTC)
    await session.commit()
    return row


async def edit_recommendation(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    user_id: uuid.UUID,
    new_quantity: int,
) -> OrderRecommendation:
    if new_quantity < 0:
        raise ValueError("quantity cannot be negative")
    row = await _get_pending(session, tenant_id, recommendation_id)
    row.status = RecommendationStatus.EDITED
    row.final_quantity = new_quantity
    row.decided_by = user_id
    row.decided_at = datetime.now(UTC)
    await session.commit()
    return row


async def reject_recommendation(
    session: AsyncSession, tenant_id: uuid.UUID, recommendation_id: uuid.UUID, user_id: uuid.UUID
) -> OrderRecommendation:
    row = await _get_pending(session, tenant_id, recommendation_id)
    row.status = RecommendationStatus.REJECTED
    row.decided_by = user_id
    row.decided_at = datetime.now(UTC)
    await session.commit()
    return row


async def list_pending_recommendations(
    session: AsyncSession, tenant_id: uuid.UUID
) -> list[OrderRecommendation]:
    await _set_tenant(session, tenant_id)
    result = await session.execute(
        select(OrderRecommendation).where(
            OrderRecommendation.tenant_id == tenant_id,
            OrderRecommendation.status == RecommendationStatus.PENDING,
        )
    )
    return list(result.scalars().all())
