"""Pydantic models shared across modules (sources, topics, personas, briefings)."""

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Stable, URL-safe identifiers: lower-case words joined by hyphens.
_ID_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"

# Which rule produced a publication date; see `briefing.sources.extract_date`.
DateRule = Literal[
    "url_date",
    "url_month",
    "text_in_url_month",
    "label_published",
    "label_updated",
    "text_head",
]


class Topic(BaseModel):
    """A subject that sources are tagged with. `description` is what gets embedded."""

    # Unknown keys are rejected so a typo in the YAML file is an error, not silently ignored.
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=_ID_PATTERN)
    label: str = Field(min_length=1)
    description: str = Field(min_length=20)


class Persona(BaseModel):
    """Who a briefing is for: a position, a location and the topics they follow."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=_ID_PATTERN)
    position: str = Field(min_length=1)
    location: str = Field(min_length=1)
    topic_ids: tuple[str, ...] = Field(min_length=1)


class Source(BaseModel):
    """One scraped web page from the input file, as loaded (text is not yet cleaned)."""

    model_config = ConfigDict(frozen=True)

    id: str
    url: str
    title: str
    description: str
    text: str


class PublicationDate(BaseModel):
    """A derived publication date and how it was found."""

    model_config = ConfigDict(frozen=True)

    value: date
    rule: DateRule
    # "month" means only the year and month are known; `value` is then the first of the month.
    precision: Literal["day", "month"] = "day"


class Passage(BaseModel):
    """A paragraph-sized piece of a selected source, and the persona topic it matches best.

    `id` is what the model cites; the application maps it back to `source_url`.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    source_url: str
    text: str
    topic_id: str
    score: float


class DraftBullet(BaseModel):
    """One finding written by the model, with the ids of the passages it rests on."""

    text: str
    passage_ids: list[str]


class DraftSection(BaseModel):
    """The model's bullets for one topic."""

    topic_id: str
    bullets: list[DraftBullet]


class BriefingDraft(BaseModel):
    """The structured answer requested from the model (M5). Unchecked until validated."""

    sections: list[DraftSection]


class BriefingSource(BaseModel):
    """A source listed in a briefing under its citation number."""

    number: int
    title: str
    url: str
    # For a source dated only to a month, the first day of that month: show it as a month.
    published: date | None = None


class Briefing(BaseModel):
    """A finished briefing: Markdown plus the sources it cites and what validation removed."""

    persona_id: str
    markdown: str
    sources: list[BriefingSource]
    dropped_bullets: int = 0
    dropped_citations: int = 0
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PreparedSource(BaseModel):
    """A source with its cleaned text and derived publication date (None if undeterminable)."""

    model_config = ConfigDict(frozen=True)

    source: Source
    clean_text: str
    published: PublicationDate | None
