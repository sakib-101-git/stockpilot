"""Celery application. Background jobs run here, never inside an API request."""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "stockpilot",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["workers.tasks_import"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)
