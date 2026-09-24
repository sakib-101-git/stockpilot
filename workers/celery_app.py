"""Celery application. Background jobs run here, never inside an API request."""

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings
from app.core.logging import configure_logging

configure_logging()

celery_app = Celery(
    "stockpilot",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["workers.tasks_import", "workers.tasks_forecast"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)

celery_app.conf.beat_schedule = {
    "nightly-forecasts": {
        "task": "workers.run_nightly_forecasts",
        "schedule": crontab(hour=2, minute=0),
    },
}


def run_async(coro):
    """Run an async function whether or not an event loop is already active.

    In production (a real Celery worker), there is no running loop, so
    asyncio.run() works normally. In tests, task_always_eager executes the
    task inline inside pytest-asyncio's loop, so the coroutine is run on a
    separate thread instead, to avoid nesting event loops.
    """
    import asyncio
    import concurrent.futures

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
