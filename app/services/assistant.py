"""AI assistant: a Gemini chat session with tools bound to one tenant.

Every tool creates its own database engine, scoped entirely to whichever
event loop actually runs it, rather than reusing a session created
outside — the same pattern workers/tasks_import.py already established.
An asyncpg connection is bound to the loop that created it; sharing one
across a thread boundary corrupts it. The LLM never sees or can influence
tenant_id, so it cannot be tricked into crossing a tenant boundary.
Read-only: nothing here approves, rejects, or edits a real order.
"""

import asyncio
import concurrent.futures
import uuid
from datetime import date as date_cls
from pathlib import Path

from google import genai
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from ml.explain import explain_forecast

MODEL_NAME = "gemini-3.5-flash-lite"
CALENDAR_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "calendar.parquet"

SYSTEM_INSTRUCTION = (
    "You are Stockpilot's inventory assistant. You answer questions about "
    "a shop's demand forecasts, reorder status, and purchasing "
    "recommendations using the tools provided. Always use a tool to look "
    "up real data rather than guessing or estimating numbers yourself. "
    "If a tool returns an error or says something is not available, say "
    "so plainly rather than making up a plausible-sounding answer. You "
    "cannot approve, reject, or edit any order yourself — if asked to "
    "take one of those actions, explain that the user needs to do that "
    "themselves in the Recommendations page."
)


def _run_async(coro):
    """Runs a coroutine whether or not a loop is already active, mirroring
    workers.celery_app.run_async.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def _with_tenant_session(tenant_id: uuid.UUID, fn):
    """Opens a fresh engine/session scoped to this call, sets the tenant
    context, runs fn(session), and disposes the engine — never reuses a
    session across an event-loop boundary.
    """
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            await session.execute(
                text("SELECT set_config('app.current_tenant', :t, true)"),
                {"t": str(tenant_id)},
            )
            return await fn(session)
    finally:
        await engine.dispose()


class Assistant:
    def __init__(self, tenant_id: uuid.UUID) -> None:
        self._tenant_id = tenant_id
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._chat = self._client.chats.create(
            model=MODEL_NAME,
            config={
                "tools": [
                    self._get_forecast,
                    self._explain_forecast,
                    self._get_reorder_status,
                    self._run_budget_optimization,
                    self._list_pending_recommendations,
                ],
                "system_instruction": SYSTEM_INSTRUCTION,
            },
        )

    def _get_forecast(self, product_id: str) -> str:
        """Returns the 28-day demand forecast for a product, given its
        product_id (a UUID string). Returns the point estimate and upper
        bound for each of the next 28 days.
        """
        from app.db.models import Forecast

        async def _fetch(session: AsyncSession) -> str:
            latest = await session.execute(
                select(Forecast.generated_at)
                .where(Forecast.product_id == uuid.UUID(product_id))
                .order_by(Forecast.generated_at.desc())
                .limit(1)
            )
            ts = latest.scalar_one_or_none()
            if ts is None:
                return "No forecast available for this product."
            rows = await session.execute(
                select(Forecast)
                .where(Forecast.product_id == uuid.UUID(product_id), Forecast.generated_at == ts)
                .order_by(Forecast.target_date)
            )
            forecasts = rows.scalars().all()
            lines = [
                f"{f.target_date}: point={f.point_estimate}, upper_bound={f.upper_bound}"
                for f in forecasts
            ]
            return "\n".join(lines)

        try:
            return _run_async(_with_tenant_session(self._tenant_id, _fetch))
        except Exception as exc:
            return f"Error looking up forecast: {exc}"

    def _explain_forecast(self, product_id: str, target_date: str) -> str:
        """Explains why the model predicted a given forecast for a
        product on a specific date (YYYY-MM-DD), by listing which
        features had the largest impact on that prediction.
        """

        async def _fetch(session: AsyncSession) -> str:
            year, month, day = (int(p) for p in target_date.split("-"))
            result = await explain_forecast(
                session,
                self._tenant_id,
                uuid.UUID(product_id),
                date_cls(year, month, day),
                CALENDAR_PATH,
            )
            lines = [
                f"{r['feature']}: value={r['value']}, impact={r['impact']}" for r in result[:8]
            ]
            return "\n".join(lines)

        try:
            return _run_async(_with_tenant_session(self._tenant_id, _fetch))
        except Exception as exc:
            return f"Error explaining forecast: {exc}"

    def _get_reorder_status(self, product_id: str) -> str:
        """Checks whether a product needs to be reordered right now,
        given its product_id (a UUID string). Returns current stock, the
        reorder point, whether an order should be placed, and how much.
        """
        from app.services.reorder import get_reorder_recommendation

        async def _fetch(session: AsyncSession) -> str:
            rec = await get_reorder_recommendation(session, uuid.UUID(product_id))
            return (
                f"current_stock={rec.current_stock}, reorder_point={rec.reorder_point}, "
                f"should_reorder={rec.should_reorder}, order_quantity={rec.order_quantity}"
            )

        try:
            return _run_async(_with_tenant_session(self._tenant_id, _fetch))
        except Exception as exc:
            return f"Error checking reorder status: {exc}"

    def _run_budget_optimization(self, budget: float) -> str:
        """Given a purchasing budget, returns which products should be
        reordered to make the best use of that budget, using the same
        optimizer the Recommendations page uses. Does not place or save
        any order — this is a preview only.
        """
        from app.services.optimizer import optimize_budget

        async def _fetch(session: AsyncSession) -> str:
            result = await optimize_budget(session, self._tenant_id, budget)
            if not result.orders:
                return f"No products need reordering within a budget of {budget}."
            lines = [f"total_cost={result.total_cost} of budget={result.budget}"]
            lines += [
                f"{o.sku}: qty={o.order_quantity}, cost={o.cost}, priority={o.priority}"
                for o in result.orders
            ]
            return "\n".join(lines)

        try:
            return _run_async(_with_tenant_session(self._tenant_id, _fetch))
        except Exception as exc:
            return f"Error running budget optimization: {exc}"

    def _list_pending_recommendations(self) -> str:
        """Lists the purchasing recommendations currently awaiting the
        user's approval, edit, or rejection.
        """
        from app.db.models import Product
        from app.services.order_recommendations import list_pending_recommendations

        async def _fetch(session: AsyncSession) -> str:
            rows = await list_pending_recommendations(session, self._tenant_id)
            if not rows:
                return "No pending recommendations."
            product_ids = [r.product_id for r in rows]
            result = await session.execute(select(Product).where(Product.id.in_(product_ids)))
            skus = {p.id: p.sku for p in result.scalars().all()}
            return "\n".join(
                f"id={r.id}, sku={skus.get(r.product_id, 'unknown')}, "
                f"qty={r.suggested_quantity}, cost={r.suggested_cost}"
                for r in rows
            )

        try:
            return _run_async(_with_tenant_session(self._tenant_id, _fetch))
        except Exception as exc:
            return f"Error listing pending recommendations: {exc}"

    def ask(self, question: str) -> str:
        response = self._chat.send_message(question)
        return response.text
