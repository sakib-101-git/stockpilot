"""Runs a validated CSV import against the database for one tenant."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ImportJob, ImportStatus, Product
from app.services.importer import RowError, format_error_report, parse_products_csv


async def run_import(
    session: AsyncSession, job_id: uuid.UUID, tenant_id: uuid.UUID, file_path: str
) -> None:
    """Parse the file at `file_path`, create products, and update the job's status.

    `tenant_id` is passed in explicitly rather than read off the job row,
    because the job lookup itself is subject to row-level security: without
    the tenant context set first, that first SELECT would see no rows at all.
    Each commit ends the transaction and clears the transaction-local
    app.current_tenant setting, so it is re-applied after every commit that
    is followed by more tenant-scoped work.

    Never raises: any failure is recorded on the job itself as `FAILED`.
    """

    async def set_tenant() -> None:
        await session.execute(
            text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )

    await set_tenant()
    job = await session.get(ImportJob, job_id)
    if job is None:
        return

    job.status = ImportStatus.PROCESSING
    await session.commit()

    try:
        content = Path(file_path).read_text()
    except OSError as exc:
        await set_tenant()
        job.status = ImportStatus.FAILED
        job.error_report = f"could not read file: {exc}"
        job.completed_at = datetime.now(UTC)
        await session.commit()
        return

    parsed = parse_products_csv(content)

    await set_tenant()
    existing = await session.execute(select(Product.sku).where(Product.tenant_id == tenant_id))
    existing_skus = set(existing.scalars().all())

    created = 0
    still_valid = []
    for row in parsed.valid_rows:
        if row.sku in existing_skus:
            parsed.errors.append(
                RowError(
                    row=len(parsed.valid_rows) + len(parsed.errors),
                    message=f"sku '{row.sku}' already exists for this tenant",
                )
            )
            continue
        session.add(Product(tenant_id=tenant_id, **row.model_dump()))
        existing_skus.add(row.sku)
        still_valid.append(row)
        created += 1
    parsed.valid_rows = still_valid

    job.total_rows = parsed.total_rows
    job.error_rows = len(parsed.errors)
    job.error_report = format_error_report(parsed.errors)
    job.status = ImportStatus.SUCCEEDED if created > 0 or not parsed.errors else ImportStatus.FAILED
    job.completed_at = datetime.now(UTC)
    await session.commit()
