from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Stockpilot"
    environment: str = "local"
    database_url: str
    redis_url: str


settings = Settings()
