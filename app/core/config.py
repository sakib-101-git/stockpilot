from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Stockpilot"
    environment: str = "local"
    database_url: str
    redis_url: str
    migration_database_url: str | None = None
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    gemini_api_key: str = ""

    # When true (set in production, where no separate Celery worker
    # process runs), background work — CSV import, the nightly forecast
    # job — executes inline within the request/admin-call itself,
    # reusing the exact same async functions Celery normally dispatches
    # to, rather than duplicating the logic. False locally, where a real
    # worker container is available via docker compose.
    inline_tasks: bool = False

    # Shared secret for the admin-only nightly job trigger endpoint,
    # called by a scheduled GitHub Actions workflow in production. Not
    # a real user's JWT — this endpoint runs across every tenant and
    # must only be callable by that one trusted automated caller.
    admin_job_secret: str = ""


settings = Settings()