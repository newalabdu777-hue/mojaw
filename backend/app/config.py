"""Runtime configuration for the non-production starter API."""
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SCHOOL_", env_file=".env", extra="ignore")

    app_name: str = "School Management System API"
    app_version: str = "0.2.0"
    environment: str = "development"
    auth_required: bool = False
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
