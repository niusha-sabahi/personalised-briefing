"""Application settings, loaded from the environment or a local `.env` file."""

from datetime import date
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration. See `.env.example` for what each option does.

    Model names and the API key have no defaults on purpose: nothing about the
    OpenAI account or model choice is hard-coded.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: SecretStr
    generation_model: str
    embedding_model: str

    sources_path: Path = Path("sources_06-05-25.json")
    topics_path: Path = Path("topics.yaml")
    cache_path: Path = Path(".cache/embeddings")

    # Newest source is 2025-05-06; the task allows sources up to one month older.
    cutoff_date: date = date(2025, 4, 6)

    tagging_threshold: float = Field(default=0.35, ge=-1.0, le=1.0)
    max_tags_per_source: int = Field(default=3, ge=1)
    top_k: int = Field(default=8, ge=1)
    per_topic_min: int = Field(default=1, ge=0)

    log_level: str = "INFO"
