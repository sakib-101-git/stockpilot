"""Budget-constrained reorder optimizer.

Given a tenant-wide purchasing budget, decides which products to fully
reorder (to the order_quantity app.services.reorder already computed,
respecting MOQ/pack size) so as to maximize total stockout-risk reduction
without exceeding the budget.

This is a 0/1 knapsack: each product is either fully reordered or not.
Partial orders are not modeled — ordering half of a product's buffer still
leaves it exposed to the same stockout risk during the lead-time window,
so partial coverage is not meaningfully better than no coverage here.

Solved with OR-Tools' CP-SAT solver.
"""

import uuid
from dataclasses import dataclass

from ortools.sat.python import cp_model
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, ProductSupplier
from app.services.reorder import ReorderRecommendation, get_reorder_recommendation


@dataclass
class OptimizedOrder:
    product_id: uuid.UUID
    sku: str
    order_quantity: int
    cost: float
    priority: float


@dataclass
class OptimizationResult:
    budget: float
    total_cost: float
    orders: list[OptimizedOrder]
    skipped_product_ids: list[uuid.UUID]


def _priority(rec: ReorderRecommendation) -> float:
    """Fraction of the reorder point currently uncovered — scale-free, so a
    low-volume product isn't systematically deprioritized against a
    high-volume one just because its raw unit shortfall is smaller.
    """
    if rec.reorder_point <= 0:
        return 0.0
    raw_need = max(0.0, rec.reorder_point - rec.current_stock)
    return min(1.0, raw_need / rec.reorder_point)


async def _candidate_orders(
    session: AsyncSession, tenant_id: uuid.UUID
) -> list[tuple[Product, ProductSupplier, ReorderRecommendation]]:
    products = (
        (await session.execute(select(Product).where(Product.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    candidates = []
    for product in products:
        supplier_link = (
            await session.execute(
                select(ProductSupplier).where(ProductSupplier.product_id == product.id)
            )
        ).scalar_one_or_none()
        if supplier_link is None:
            continue
        try:
            rec = await get_reorder_recommendation(session, product.id)
        except ValueError:
            continue
        if rec.should_reorder:
            candidates.append((product, supplier_link, rec))
    return candidates


async def optimize_budget(
    session: AsyncSession, tenant_id: uuid.UUID, budget: float
) -> OptimizationResult:
    candidates = await _candidate_orders(session, tenant_id)
    if not candidates:
        return OptimizationResult(budget=budget, total_cost=0.0, orders=[], skipped_product_ids=[])

    model = cp_model.CpModel()
    budget_cents = round(budget * 100)

    chosen = []
    costs_cents = []
    priorities_scaled = []
    for product, supplier_link, rec in candidates:
        cost = rec.order_quantity * float(supplier_link.unit_cost)
        costs_cents.append(round(cost * 100))
        priorities_scaled.append(round(_priority(rec) * 1000))
        chosen.append(model.NewBoolVar(f"order_{product.id}"))

    model.Add(sum(c * v for c, v in zip(costs_cents, chosen, strict=True)) <= budget_cents)
    model.Maximize(sum(p * v for p, v in zip(priorities_scaled, chosen, strict=True)))

    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    orders: list[OptimizedOrder] = []
    skipped: list[uuid.UUID] = []
    total_cost = 0.0

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for (product, supplier_link, rec), var in zip(candidates, chosen, strict=True):
            cost = rec.order_quantity * float(supplier_link.unit_cost)
            if solver.Value(var):
                orders.append(
                    OptimizedOrder(
                        product_id=product.id,
                        sku=product.sku,
                        order_quantity=rec.order_quantity,
                        cost=round(cost, 2),
                        priority=round(_priority(rec), 3),
                    )
                )
                total_cost += cost
            else:
                skipped.append(product.id)
    else:
        skipped = [p.id for p, _, _ in candidates]

    return OptimizationResult(
        budget=budget,
        total_cost=round(total_cost, 2),
        orders=orders,
        skipped_product_ids=skipped,
    )
