"""Explicit configuration; never load another project's .env."""
from functools import lru_cache
from pathlib import Path
from typing import Literal
from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore", populate_by_name=True)
    app_name: str = "TripPilot"
    app_version: str = "1.0.0"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000"
    amap_api_key: SecretStr = SecretStr("")
    unsplash_access_key: SecretStr = SecretStr("")
    unsplash_secret_key: SecretStr = SecretStr("")
    llm_api_key: SecretStr = Field(default=SecretStr(""), validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"))
    llm_base_url: str = Field(default="https://api.openai.com/v1", validation_alias=AliasChoices("LLM_BASE_URL", "OPENAI_BASE_URL"))
    llm_model: str = Field(default="", validation_alias=AliasChoices("LLM_MODEL_ID", "OPENAI_MODEL"))
    llm_timeout: int = Field(default=60, ge=1, le=300)
    llm_max_calls_per_plan: int = Field(default=4, ge=1, le=10)
    llm_max_prompt_chars: int = Field(default=60000, ge=1000, le=200000)
    tool_timeout: float = Field(default=20, gt=0, le=120)
    tool_total_timeout: float = Field(default=50, gt=0, le=300)
    tool_max_attempts: int = Field(default=2, ge=1, le=3)
    tool_concurrency: int = Field(default=3, ge=1, le=8)
    redis_url: SecretStr = SecretStr("")
    redis_timeout: float = Field(default=0.3, gt=0, le=3)
    database_url: SecretStr = SecretStr("")
    checkpoint_path: str = ""
    route_max_points: int = Field(default=6, ge=2, le=10)
    route_concurrency: int = Field(default=3, ge=1, le=8)
    route_leg_timeout: float = Field(default=60, gt=0, le=180)
    route_matrix_timeout: float = Field(default=90, gt=0, le=300)
    planner_repair_attempts: int = Field(default=1, ge=0, le=2)
    planner_max_response_chars: int = Field(default=50000, ge=1000, le=200000)
    max_replan_attempts: int = Field(default=1, ge=0, le=2)
    rag_knowledge_path: str = ""
    rag_max_evidence_per_poi: int = Field(default=3, ge=1, le=10)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    def get_cors_origins_list(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]

@lru_cache
def get_settings() -> Settings:
    return Settings()

def validate_config(settings: Settings | None = None) -> None:
    from .errors import ConfigurationError
    config = settings or get_settings()
    if not (config.amap_api_key.get_secret_value().strip() and config.llm_api_key.get_secret_value().strip() and config.llm_model.strip()):
        raise ConfigurationError()

