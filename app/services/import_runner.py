"""Runs a validated CSV import against the database for one tenant."""

import uuid
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ImportJob, ImportStatus, Product
from app.services.importer import format_error_report, parse_products_csv


async def run_import(session: AsyncSession, job_id: uuid.UUID, file_path: str) -> None:
    """Parse the file at `file_path`, create products, and update the job's status.

    Never raises: any failure is recorded on the job itself as `FAILED`.
    """
    job = await session.get(ImportJob, job_id)
    if job is None:
        return

    job.status = ImportStatus.PROCESSING
    await session.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
        {"tenant_id": str(job.tenant_id)},
    )
    await session.commit()

    try:
        content = Path(file_path).read_text()
    except OSError as exc:
        job.status = ImportStatus.FAILED
        job.error_report = f"could not read file: {exc}"
        job.completed_at = _now()
        await session.commit()
        return

    parsed = parse_products_csv(content)

    existing = await session.execute(select(Product.sku).where(Product.tenant_id == job.tenant_id))
    existing_skus = set(existing.scalars().all())

    created = 0
    for row in parsed.valid_rows:
        if row.sku in existing_skus:
            parsed.errors.append(
                _duplicate_in_db_error(row.sku, len(parsed.valid_rows) + len(parsed.errors))
            )
            continue
        session.add(Product(tenant_id=job.tenant_id, **row.model_dump()))
        existing_skus.add(row.sku)
        created += 1

    job.total_rows = parsed.total_rows
    job.error_rows = len(parsed.errors)
    job.error_report = format_error_report(parsed.errors)
    job.status = ImportStatus.SUCCEEDED if created > 0 or not parsed.errors else ImportStatus.FAILED
    job.completed_at = _now()
    await session.commit()


def _duplicate_in_db_error(sku: str, row_number: int):
    from app.services.importer import RowError

    return RowError(row=row_number, message=f"sku '{sku}' already exists for this tenant")


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)
