"""Background import tasks."""

import uuid

from workers.celery_app import celery_app, run_async


@celery_app.task(name="workers.ping")
def ping() -> str:
    """Smoke-test task: proves the broker and worker are wired up correctly."""
    return "pong"


@celery_app.task(name="workers.run_product_import")
def run_product_import(job_id: str, tenant_id: str, file_path: str) -> None:
    """Entry point Celery calls. Bridges into the async import logic."""
    run_async(_run_product_import_async(job_id, tenant_id, file_path))


async def _run_product_import_async(job_id: str, tenant_id: str, file_path: str) -> None:
    """Each task execution gets its own engine, scoped to its own event loop —
    the shared app engine's connections are bound to whichever loop created
    them, so reusing it across threads/loops causes silent failures.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import settings
    from app.services.import_runner import run_import

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as session:
            await run_import(session, uuid.UUID(job_id), uuid.UUID(tenant_id), file_path)
    finally:
        await engine.dispose()
