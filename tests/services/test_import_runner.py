import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models import ImportJob, ImportStatus, Product
from app.services.import_runner import run_import
from tests.helpers import register


async def _make_job(db_engine: AsyncEngine, tenant_id: uuid.UUID) -> uuid.UUID:
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        job = ImportJob(tenant_id=tenant_id, filename="test.csv")
        session.add(job)
        await session.commit()
        return job.id


async def _get_job(db_engine: AsyncEngine, job_id: uuid.UUID) -> ImportJob:
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        return await session.get(ImportJob, job_id)


async def test_valid_file_creates_products_and_marks_succeeded(
    client, db_engine: AsyncEngine, tmp_path: Path
) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    job_id = await _make_job(db_engine, tenant_id)

    csv_path = tmp_path / "products.csv"
    csv_path.write_text("sku,name,category\nA1,Widget,Tools\nB2,Gadget,\n")

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        await run_import(session, job_id, tenant_id, str(csv_path))

    job = await _get_job(db_engine, job_id)
    assert job.status == ImportStatus.SUCCEEDED
    assert job.total_rows == 2
    assert job.error_rows == 0
    assert job.completed_at is not None

    async with maker() as session:
        result = await session.execute(select(Product).where(Product.tenant_id == tenant_id))
        skus = {p.sku for p in result.scalars().all()}
    assert skus == {"A1", "B2"}


async def test_file_with_only_bad_rows_is_marked_failed(
    client, db_engine: AsyncEngine, tmp_path: Path
) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    job_id = await _make_job(db_engine, tenant_id)

    csv_path = tmp_path / "products.csv"
    csv_path.write_text("sku,name\n,Bad Row\n")

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        await run_import(session, job_id, tenant_id, str(csv_path))

    job = await _get_job(db_engine, job_id)
    assert job.status == ImportStatus.FAILED
    assert job.error_rows == 1
    assert "row 2" in job.error_report


async def test_sku_already_in_database_is_reported_as_an_error(
    client, db_engine: AsyncEngine, tmp_path: Path
) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        session.add(Product(tenant_id=tenant_id, sku="A1", name="Existing"))
        await session.commit()

    job_id = await _make_job(db_engine, tenant_id)
    csv_path = tmp_path / "products.csv"
    csv_path.write_text("sku,name\nA1,Widget\nB2,Gadget\n")

    async with maker() as session:
        await run_import(session, job_id, tenant_id, str(csv_path))

    job = await _get_job(db_engine, job_id)
    assert job.status == ImportStatus.SUCCEEDED
    assert job.error_rows == 1
    assert "already exists" in job.error_report

    async with maker() as session:
        result = await session.execute(select(Product).where(Product.tenant_id == tenant_id))
        skus = {p.sku for p in result.scalars().all()}
    assert skus == {"A1", "B2"}


async def test_products_land_in_the_correct_tenant_only(
    client, db_engine: AsyncEngine, tmp_path: Path
) -> None:
    user_a = await register(client, "Shop A", "a@example.com")
    user_b = await register(client, "Shop B", "b@example.com")
    tenant_a, tenant_b = uuid.UUID(user_a["tenant_id"]), uuid.UUID(user_b["tenant_id"])

    job_id = await _make_job(db_engine, tenant_a)
    csv_path = tmp_path / "products.csv"
    csv_path.write_text("sku,name\nA1,Widget\n")

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        await run_import(session, job_id, tenant_a, str(csv_path))

    async with maker() as session:
        result_a = await session.execute(select(Product).where(Product.tenant_id == tenant_a))
        result_b = await session.execute(select(Product).where(Product.tenant_id == tenant_b))
    assert len(result_a.scalars().all()) == 1
    assert len(result_b.scalars().all()) == 0


async def test_missing_file_marks_the_job_failed_without_raising(
    client, db_engine: AsyncEngine
) -> None:
    user = await register(client, "Shop A", "a@example.com")
    tenant_id = uuid.UUID(user["tenant_id"])
    job_id = await _make_job(db_engine, tenant_id)

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        await run_import(session, job_id, tenant_id, "/nonexistent/path.csv")

    job = await _get_job(db_engine, job_id)
    assert job.status == ImportStatus.FAILED
    assert "could not read file" in job.error_report
