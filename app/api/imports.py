import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_owner
from app.db.models import ImportJob, User
from app.db.session import get_session
from app.schemas.import_job import ImportJobRead

router = APIRouter(prefix="/imports", tags=["imports"])

UPLOAD_DIR = Path("/tmp/stockpilot-uploads")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


@router.post("", response_model=ImportJobRead, status_code=status.HTTP_201_CREATED)
async def create_import(
    file: UploadFile,
    current_user: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> ImportJob:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=422, detail="only .csv files are accepted")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large (max 10 MB)")

    job = ImportJob(tenant_id=current_user.tenant_id, filename=file.filename)
    session.add(job)
    await session.commit()

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_path = UPLOAD_DIR / f"{job.id}.csv"
    file_path.write_bytes(content)

    from app.core.config import settings

    if settings.inline_tasks:
        from workers.tasks_import import _run_product_import_async

        await _run_product_import_async(str(job.id), str(current_user.tenant_id), str(file_path))
    else:
        from workers.tasks_import import run_product_import

        run_product_import.delay(str(job.id), str(current_user.tenant_id), str(file_path))

    await session.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
        {"tenant_id": str(current_user.tenant_id)},
    )
    await session.refresh(job)

    return job


@router.get("/{job_id}", response_model=ImportJobRead)
async def get_import(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ImportJob:
    result = await session.execute(
        select(ImportJob).where(
            ImportJob.id == job_id,
            ImportJob.tenant_id == current_user.tenant_id,
        )
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Import job not found")
    return job
