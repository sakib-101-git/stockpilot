from workers.celery_app import celery_app
from workers.tasks_import import ping


def test_ping_task_runs_eagerly() -> None:
    celery_app.conf.task_always_eager = True
    try:
        result = ping.delay()
        assert result.get(timeout=5) == "pong"
    finally:
        celery_app.conf.task_always_eager = False
