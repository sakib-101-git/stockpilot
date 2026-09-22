from fastapi import FastAPI

from app.api import auth, forecasts, health, imports, products, suppliers, users
from app.core.config import settings

app = FastAPI(title=settings.app_name)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(products.router)
app.include_router(suppliers.router)
app.include_router(imports.router)
app.include_router(forecasts.router)
