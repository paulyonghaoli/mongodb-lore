from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_readonly_uri: str = ""
    mongodb_db: str = "lore"

    anthropic_api_key: str = ""
    lore_model: str = "claude-opus-5-5"

    voyage_api_key: str = ""
    voyage_model: str = "voyage-4"
    embedding_dim: int = 1024
    embedding_provider: str = "voyage"  # voyage | hash

    vector_backend: str = "atlas"  # atlas | local

    # Guard: hard cap on rows returned to the agent and the interface
    max_result_rows: int = 500


@lru_cache
def get_settings() -> Settings:
    return Settings()
