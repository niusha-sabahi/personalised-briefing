"""Application settings, loaded from the environment or a local `.env` file."""

import logging
from datetime import date
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
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

    # Calibrated on the real sources (`briefing tags`): unrelated pages score about 0.2 against
    # a topic and on-topic pages 0.4 to 0.6. Tags only build the candidate pool and passage
    # matching does the precise filtering, so this favours recall: 0.30 keeps thin topics such
    # as venture capital supplied, and the cap of 4 stops multi-topic policy pages losing
    # their weaker health tags.
    tagging_threshold: float = Field(default=0.30, ge=-1.0, le=1.0)
    max_tags_per_source: int = Field(default=4, ge=1)
    # Raised from 8 and 1 after the first live `briefing passages` runs: with one source per
    # topic, thin topics such as venture capital were met by a source that was mainly about
    # something else. Two per topic, taken in rounds, brings in a second dedicated source.
    top_k: int = Field(default=10, ge=1)
    per_topic_min: int = Field(default=2, ge=0)

    # A passage must score at least this against a persona topic to be used for it (M8).
    # Calibrated with `briefing passages`: 0.30 let through 85% of passages, while 0.40 keeps
    # to the on-topic band (unrelated text scores about 0.2, on-topic 0.4 to 0.6).
    passage_threshold: float = Field(default=0.40, ge=-1.0, le=1.0)
    # Each persona topic takes its best passages across the chosen sources, and no one
    # source supplies more than the second limit, so a briefing is not one article. Raised
    # in steps from 3 and 3 after the live briefings: passages are picked for being about a
    # topic, which favours background over news, so the model needs more to choose from, and
    # it has proved good at ignoring the junk among them.
    max_passages_per_topic: int = Field(default=7, ge=1)
    max_passages_per_source: int = Field(default=5, ge=1)
    # Added to a passage's score, for ranking only, when the passage itself states a date inside
    # the recency window. Evergreen explainers outscore dated news by 0.1 to 0.2 on topic
    # similarity, so without it the model never saw the news. Calibrated offline on the real
    # passages: 0.15 turns the founder's AI picks into a mix of news and explainers, while the
    # weakest dated pick still scores 0.46. At 0.22 it drops to 0.41, barely above the threshold.
    recency_bonus: float = Field(default=0.15, ge=0.0, le=0.5)
    # Optional: the most one source may give to a single topic. Off by default. At 2 it made
    # the live briefings thinner (a source's strongest passages were pushed to another topic
    # and the next-best sources, often weaker, filled in) without bringing in the AI news page.
    max_passages_per_source_per_topic: int | None = Field(default=None, ge=1)

    # The OpenAI client retries rate limits, timeouts and server errors with backoff (S13).
    openai_timeout_seconds: float = Field(default=60.0, gt=0)
    openai_max_retries: int = Field(default=3, ge=0)

    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def _known_log_level(cls, value: str) -> str:
        """Accept any standard logging level name, in any case."""
        level = value.upper()
        if level not in logging.getLevelNamesMapping():
            raise ValueError(f"unknown log level {value!r}")
        return level
