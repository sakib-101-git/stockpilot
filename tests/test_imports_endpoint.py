import pytest
from httpx import AsyncClient

from tests.helpers import PASSWORD, login_headers, register
from workers.celery_app import celery_app


@pytest.fixture(autouse=True)
def _eager_celery():
    celery_app.conf.task_always_eager = True
    yield
    celery_app.conf.task_always_eager = False


async def test_uploading_a_valid_csv_creates_products(client: AsyncClient) -> None:
    await register(client, "Shop A", "a@example.com")
    headers = await login_headers(client, "a@example.com")

    csv_bytes = b"sku,name,category\nA1,Widget,Tools\n"
    response = await client.post(
        "/imports",
        headers=headers,
        files={"file": ("products.csv", csv_bytes, "text/csv")},
    )

    assert response.status_code == 201
    job = response.json()
    assert job["status"] == "succeeded"
    assert job["total_rows"] == 1
    assert job["error_rows"] == 0


async def test_non_csv_file_is_rejected(client: AsyncClient) -> None:
    await register(client, "Shop A", "a@example.com")
    headers = await login_headers(client, "a@example.com")

    response = await client.post(
        "/imports",
        headers=headers,
        files={"file": ("products.txt", b"sku,name\nA1,Widget\n", "text/plain")},
    )
    assert response.status_code == 422


async def test_staff_cannot_create_an_import(client: AsyncClient) -> None:
    await register(client, "Shop A", "a@example.com")
    owner_headers = await login_headers(client, "a@example.com")
    await client.post(
        "/users",
        headers=owner_headers,
        json={"email": "staff@example.com", "password": PASSWORD},
    )
    staff_headers = await login_headers(client, "staff@example.com")

    response = await client.post(
        "/imports",
        headers=staff_headers,
        files={"file": ("products.csv", b"sku,name\nA1,Widget\n", "text/csv")},
    )
    assert response.status_code == 403


async def test_creating_an_import_without_a_token_is_401(client: AsyncClient) -> None:
    response = await client.post(
        "/imports", files={"file": ("products.csv", b"sku,name\n", "text/csv")}
    )
    assert response.status_code == 401


async def test_get_import_returns_the_job(client: AsyncClient) -> None:
    await register(client, "Shop A", "a@example.com")
    headers = await login_headers(client, "a@example.com")

    created = await client.post(
        "/imports",
        headers=headers,
        files={"file": ("products.csv", b"sku,name\nA1,Widget\n", "text/csv")},
    )
    job_id = created.json()["id"]

    response = await client.get(f"/imports/{job_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["id"] == job_id


async def test_another_tenants_import_job_looks_like_it_does_not_exist(
    client: AsyncClient,
) -> None:
    await register(client, "Shop A", "a@example.com")
    await register(client, "Shop B", "b@example.com")
    headers_a = await login_headers(client, "a@example.com")
    headers_b = await login_headers(client, "b@example.com")

    created = await client.post(
        "/imports",
        headers=headers_a,
        files={"file": ("products.csv", b"sku,name\nA1,Widget\n", "text/csv")},
    )
    job_id = created.json()["id"]

    response = await client.get(f"/imports/{job_id}", headers=headers_b)
    assert response.status_code == 404
