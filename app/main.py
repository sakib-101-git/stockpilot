import time

from fastapi import FastAPI, Request
from prometheus_fastapi_instrumentator import Instrumentator

from app.api import (
    auth,
    forecasts,
    health,
    imports,
    order_recommendations,
    products,
    reorder,
    suppliers,
    users,
)
from app.core.config import settings
from app.core.logging import (
    configure_logging,
    get_logger,
    log_with_fields,
    new_request_id,
    request_id_var,
)

configure_logging()
logger = get_logger("stockpilot.http")

app = FastAPI(title=settings.app_name)

Instrumentator().instrument(app).expose(app, endpoint="/metrics")


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = new_request_id()
    token = request_id_var.set(request_id)
    start = time.monotonic()
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    duration_ms = round((time.monotonic() - start) * 1000, 1)
    log_with_fields(
        logger,
        20,  # logging.INFO
        "request completed",
        method=request.method,
        path=request.url.path,
        status_code=getattr(response, "status_code", None),
        duration_ms=duration_ms,
        request_id=request_id,
    )
    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(products.router)
app.include_router(suppliers.router)
app.include_router(imports.router)
app.include_router(forecasts.router)
app.include_router(reorder.router)
app.include_router(order_recommendations.router)
