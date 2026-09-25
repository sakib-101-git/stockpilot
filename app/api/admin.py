"""Admin-only endpoints for automated, cross-tenant operations — not
reachable by any regular user's JWT. Protected by a shared secret
(ADMIN_JOB_SECRET), checked via a header, meant to be called only by a
trusted automated caller (a scheduled GitHub Actions workflow in
production).
"""

from fastapi import APIRouter, Header, HTTPException

from app.core.config import settings

router = APIRouter(prefix="/admin", tags=["admin"])


def _check_admin_secret(x_admin_secret: str | None) -> None:
    if not settings.admin_job_secret:
        raise HTTPException(
            status_code=503, detail="admin endpoints are not configured on this deployment"
        )
    if x_admin_secret != settings.admin_job_secret:
        raise HTTPException(status_code=401, detail="invalid admin secret")


@router.post("/run-nightly-job")
async def run_nightly_job(x_admin_secret: str | None = Header(default=None)) -> dict:
    _check_admin_secret(x_admin_secret)

    from workers.tasks_forecast import DEFAULT_CALENDAR_PATH, _run_nightly_forecasts_async

    result = await _run_nightly_forecasts_async(DEFAULT_CALENDAR_PATH)
    return {"results": result}