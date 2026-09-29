"""Runtime configuration for the mock service."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Connection settings loaded from the environment or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "mysql+asyncmy://root@127.0.0.1:3306/mockfastapi"
    redis_url: str = "redis://127.0.0.1:6379/0"
