"""Background import tasks. Real CSV import logic lands here in the next step."""

from workers.celery_app import celery_app


@celery_app.task(name="workers.ping")
def ping() -> str:
    """Smoke-test task: proves the broker and worker are wired up correctly."""
    return "pong"
