"""AI assistant: a Gemini chat session with tools bound to one tenant.

Every tool creates its own database engine, scoped entirely to whichever
event loop actually runs it, rather than reusing a session created
outside — the same pattern workers/tasks_import.py already established.
An asyncpg connection is bound to the loop that created it; sharing one
across a thread boundary (as this module's earlier version did) corrupts
it. The LLM never sees or can influence tenant_id, so it cannot be
tricked into crossing a tenant boundary. Read-only: nothing here
approves, rejects, or edits a real order.
"""

import asyncio
import concurrent.futures
import uuid
from pathlib import Path

from google import genai
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from ml.explain import explain_forecast

MODEL_NAME = "gemini-3.5-flash-lite"
CALENDAR_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "calendar.parquet"

SYSTEM_INSTRUCTION = (
    "You are Stockpilot's inventory assistant. You answer questions about "
    "a shop's demand forecasts and reorder status using the tools "
    "provided. Always use a tool to look up real data rather than "
    "guessing or estimating numbers yourself. If a tool returns an error "
    "or says something is not available, say so plainly rather than "
    "making up a plausible-sounding answer."
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


class Assistant:
    def __init__(self, tenant_id: uuid.UUID) -> None:
        self._tenant_id = tenant_id
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._chat = self._client.chats.create(
            model=MODEL_NAME,
            config={
                "tools": [self._get_forecast, self._explain_forecast],
                "system_instruction": SYSTEM_INSTRUCTION,
            },
        )

    def _get_forecast(self, product_id: str) -> str:
        """Returns the 28-day demand forecast for a product, given its
        product_id (a UUID string). Returns the point estimate and upper
        bound for each of the next 28 days.
        """
        from sqlalchemy import select

        from app.db.models import Forecast

        async def _fetch():
            engine = create_async_engine(settings.database_url, pool_pre_ping=True)
            try:
                maker = async_sessionmaker(engine, expire_on_commit=False)
                async with maker() as session:
                    await session.execute(
                        text("SELECT set_config('app.current_tenant', :t, true)"),
                        {"t": str(self._tenant_id)},
                    )
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
                        .where(
                            Forecast.product_id == uuid.UUID(product_id),
                            Forecast.generated_at == ts,
                        )
                        .order_by(Forecast.target_date)
                    )
                    forecasts = rows.scalars().all()
                    lines = [
                        f"{f.target_date}: point={f.point_estimate}, upper_bound={f.upper_bound}"
                        for f in forecasts
                    ]
                    return "\n".join(lines)
            finally:
                await engine.dispose()

        try:
            return _run_async(_fetch())
        except Exception as exc:
            return f"Error looking up forecast: {exc}"

    def _explain_forecast(self, product_id: str, target_date: str) -> str:
        """Explains why the model predicted a given forecast for a
        product on a specific date (YYYY-MM-DD), by listing which
        features had the largest impact on that prediction.
        """
        from datetime import date as date_cls

        async def _fetch():
            engine = create_async_engine(settings.database_url, pool_pre_ping=True)
            try:
                maker = async_sessionmaker(engine, expire_on_commit=False)
                async with maker() as session:
                    await session.execute(
                        text("SELECT set_config('app.current_tenant', :t, true)"),
                        {"t": str(self._tenant_id)},
                    )
                    year, month, day = (int(p) for p in target_date.split("-"))
                    result = await explain_forecast(
                        session,
                        self._tenant_id,
                        uuid.UUID(product_id),
                        date_cls(year, month, day),
                        CALENDAR_PATH,
                    )
                    lines = [
                        f"{r['feature']}: value={r['value']}, impact={r['impact']}"
                        for r in result[:8]
                    ]
                    return "\n".join(lines)
            finally:
                await engine.dispose()

        try:
            return _run_async(_fetch())
        except Exception as exc:
            return f"Error explaining forecast: {exc}"

    def ask(self, question: str) -> str:
        response = self._chat.send_message(question)
        return response.text
