"""Application settings, loaded from the environment or a local `.env` file."""

from datetime import date
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SOURCES_PATH = Path("sources_06-05-25.json")
DEFAULT_TOPICS_PATH = Path("topics.yaml")
DEFAULT_PERSONAS_PATH = Path("personas.yaml")
# The newest source is dated 2025-05-06; the task allows sources up to one month older.
DEFAULT_CUTOFF_DATE = date(2025, 4, 6)
DEFAULT_LATEST_DATE = date(2025, 5, 6)


class Settings(BaseSettings):
    """All runtime configuration. See `.env.example` for what each option does.

    Model names and the API key have no defaults on purpose: nothing about the
    OpenAI account or model choice is hard-coded.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: SecretStr
    generation_model: str
    embedding_model: str

    sources_path: Path = DEFAULT_SOURCES_PATH
    topics_path: Path = DEFAULT_TOPICS_PATH
    personas_path: Path = DEFAULT_PERSONAS_PATH
    cache_path: Path = Path(".cache/embeddings")

    cutoff_date: date = DEFAULT_CUTOFF_DATE
    # Dates after this are not publication dates (events, deadlines), so date extraction skips them.
    latest_date: date = DEFAULT_LATEST_DATE

    tagging_threshold: float = Field(default=0.35, ge=-1.0, le=1.0)
    max_tags_per_source: int = Field(default=3, ge=1)
    top_k: int = Field(default=8, ge=1)
    per_topic_min: int = Field(default=1, ge=0)

    log_level: str = "INFO"
