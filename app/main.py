from fastapi import FastAPI

from app.api import auth, health, users
from app.core.config import settings

app = FastAPI(title=settings.app_name)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
