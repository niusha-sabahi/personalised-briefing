"""Pydantic models shared across modules (sources, topics, personas, briefings)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

# Which rule produced a publication date; see `briefing.sources.extract_date`.
DateRule = Literal[
    "url_date",
    "url_month",
    "text_in_url_month",
    "label_published",
    "label_updated",
    "text_head",
]


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


class PreparedSource(BaseModel):
    """A source with its cleaned text and derived publication date (None if undeterminable)."""

    model_config = ConfigDict(frozen=True)

    source: Source
    clean_text: str
    published: PublicationDate | None
