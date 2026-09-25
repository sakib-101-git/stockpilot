from pydantic import field_validator
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
    inline_tasks: bool = False
    admin_job_secret: str = ""

    @field_validator("database_url", "migration_database_url")
    @classmethod
    def _translate_neon_ssl_params(cls, value: str | None) -> str | None:
        """Neon's connection strings carry ?sslmode=require&channel_binding=require,
        which asyncpg rejects outright as unrecognized keyword arguments — a
        real, documented failure mode, not a hypothetical one. asyncpg's
        SQLAlchemy dialect recognizes a plain ssl= query parameter instead,
        so sslmode is translated to it and channel_binding is dropped
        (asyncpg has no equivalent; TLS itself is still required either
        way, so this does not weaken the actual connection security).
        """
        if value is None:
            return value
        if "sslmode=" not in value:
            return value

        from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

        parsed = urlparse(value)
        params = parse_qs(parsed.query)
        sslmode = params.pop("sslmode", [None])[0]
        params.pop("channel_binding", None)
        if sslmode:
            params["ssl"] = [sslmode]
        new_query = urlencode(params, doseq=True)
        return urlunparse(parsed._replace(query=new_query))


settings = Settings()
