"""Background import tasks."""

import asyncio
import uuid

from workers.celery_app import celery_app


@celery_app.task(name="workers.ping")
def ping() -> str:
    """Smoke-test task: proves the broker and worker are wired up correctly."""
    return "pong"


@celery_app.task(name="workers.run_product_import")
def run_product_import(job_id: str, file_path: str) -> None:
    """Entry point Celery calls. Bridges into the async import logic."""
    asyncio.run(_run_product_import_async(job_id, file_path))


async def _run_product_import_async(job_id: str, file_path: str) -> None:
    from app.db.session import SessionLocal
    from app.services.import_runner import run_import

    async with SessionLocal() as session:
        await run_import(session, uuid.UUID(job_id), file_path)
