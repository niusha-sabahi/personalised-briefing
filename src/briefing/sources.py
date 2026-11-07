"""Load sources, clean scraped text and derive publication dates.

Publication dates are not in the data, so `extract_date` derives them with an
ordered list of rules, strongest first. The rule that matched is recorded so the
result can be audited (`briefing dates`). A source whose date cannot be
determined is excluded from briefings.
"""

import html
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, ValidationError

from briefing.models import PreparedSource, PublicationDate, Source

# Cleaned text shorter than this is not enough to embed or cite (S10).
MIN_CLEAN_CHARS = 200

# How far into the cleaned text to look for dates. Publication dates sit near the
# title; dates deeper in the page are usually events or references.
_HEAD_CHARS = 3000
_LABEL_SCAN_CHARS = 8000


class SourceDataError(Exception):
    """The sources file is missing, malformed or has an unexpected shape."""


class _Entry(BaseModel):
    """One entry of `reference_by_id` as it appears in the file."""

    model_config = ConfigDict(extra="ignore")

    url: str
    title: str | None = None
    description: str | None = None
    text: str | None = None


def load_sources(path: Path) -> list[Source]:
    """Load sources from the JSON file, dropping duplicate URLs.

    When several entries share a URL, the one with the longest text is kept
    (ties go to the smaller id). The result is sorted by URL so every later step
    sees the same order on every run.

    Raises:
        SourceDataError: If the file cannot be read or does not have the expected shape.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = payload["reference_by_id"].items()
        parsed = [(key, _Entry.model_validate(value)) for key, value in entries]
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ValidationError) as exc:
        raise SourceDataError(f"Cannot load sources from {path}: {exc}") from exc

    best: dict[str, Source] = {}
    for key, entry in parsed:
        candidate = Source(
            id=key,
            url=entry.url,
            title=entry.title or "",
            description=entry.description or "",
            text=entry.text or "",
        )
        current = best.get(candidate.url)
        if current is None or (-len(candidate.text), candidate.id) < (
            -len(current.text),
            current.id,
        ):
            best[candidate.url] = candidate
    return sorted(best.values(), key=lambda s: s.url)


# --- Cleaning -----------------------------------------------------------------------

_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)\s]*(?:\s+\"[^\"]*\")?\)")
_TAG = re.compile(r"<[^>\n]+>")
_SPACE = re.compile(r"[ \t ​]+")
_HAS_WORD_CHAR = re.compile(r"\w")
_HAS_DIGIT = re.compile(r"\d")
_NON_WORD = re.compile(r"[\W_]+")

# Page furniture, in two tiers so an article sentence that merely mentions one of the
# words survives. Specific consent/legal phrases are almost never article prose, so
# they are dropped even in fairly long lines (cookie banners run to a few sentences).
# Generic words ("cookies", "subscribe") are dropped only from very short lines.
_BOILERPLATE_STRONG = re.compile(
    r"(?i)\b(?:we use (?:\w+ )?cookies|this (?:site|website) uses cookies"
    r"|cookies? (?:policy|settings|preferences|notice)|accept (?:all|additional|only)"
    r"|reject (?:all|additional)|privacy (?:policy|notice)|terms (?:of|and) (?:use|conditions)"
    r"|skip to (?:main )?content|all rights reserved)\b|©"
)
_BOILERPLATE_WEAK = re.compile(
    r"(?i)\b(?:cookies?|sign up|subscribe|newsletter|follow us|share (?:this|on)"
    r"|back to top|javascript|enable js)\b"
)
_STRONG_MAX_WORDS = 60
_WEAK_MAX_WORDS = 15
_NAV_MAX_WORDS = 8
_REPEAT_MAX_WORDS = 20


def _anchor_text(match: re.Match[str]) -> str:
    """Replace a markdown link by its anchor text.

    A space is added where the link touches a letter or digit, so that
    `[Jo](url)Apr 17, 2025` becomes `Jo Apr 17, 2025` and the date stays findable.
    """
    text, source = match.group(1), match.string
    before = source[match.start() - 1] if match.start() > 0 else " "
    after = source[match.end()] if match.end() < len(source) else " "
    return (" " if before.isalnum() else "") + text + (" " if after.isalnum() else "")


def _clean_line(line: str) -> str | None:
    """Return the readable text of one line, or None if it is furniture."""
    line = _IMAGE.sub("", line)
    line = html.unescape(_TAG.sub("", line))
    only_links = not _NON_WORD.sub("", _LINK.sub("", line))
    plain = _SPACE.sub(" ", _LINK.sub(_anchor_text, line)).strip()
    words = len(plain.split())
    is_heading = plain.startswith("#")

    if not _HAS_WORD_CHAR.search(plain):
        return None
    # One- and two-word lines are menu items ("Share", "Close"), except headings and
    # lines with a digit, which can be a bare date.
    if words <= 2 and not is_heading and not _HAS_DIGIT.search(plain):
        return None
    if only_links and words < _NAV_MAX_WORDS:
        return None
    if words < _STRONG_MAX_WORDS and _BOILERPLATE_STRONG.search(plain):
        return None
    if words < _WEAK_MAX_WORDS and _BOILERPLATE_WEAK.search(plain):
        return None
    return plain


def clean_text(text: str) -> str:
    """Strip scraping noise from page text, keeping the readable paragraphs.

    Links become their anchor text, images and HTML tags are removed, and lines that
    are navigation, consent banners or other furniture are dropped. Short repeated
    lines (menus shown twice) are kept once. Paragraphs are separated by blank lines.
    """
    seen: set[str] = set()
    kept: list[str] = []
    for raw in text.splitlines():
        line = _clean_line(raw)
        if line is None:
            continue
        if len(line.split()) < _REPEAT_MAX_WORDS:
            if line in seen:
                continue
            seen.add(line)
        kept.append(line)
    return "\n\n".join(kept)


# --- Dates --------------------------------------------------------------------------

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip
_MONTH = "(?:" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + ")"

# Dates written in running text. Slash dates (04/05/2025) are deliberately not
# supported: they are day-first in the UK and month-first in the US.
_DAY_MONTH_YEAR = re.compile(
    rf"(?i)\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH})\.?,?\s+(20\d{{2}})\b"
)
_MONTH_DAY_YEAR = re.compile(
    rf"(?i)\b({_MONTH})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d{{2}})\b"
)
_ISO = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_DOTTED = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b")

# Dates in a URL path: 2025-04-24, 2025/04/24, or 20250424.
_URL_FULL = re.compile(r"(?<!\d)(20\d{2})[-/](\d{1,2})[-/](\d{1,2})(?!\d)")
_URL_COMPACT = re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)")
# A year and month only, as in /2025/04/ (blogs) or /2025-04/ (upload folders).
_URL_MONTH = re.compile(r"/(20\d{2})[/-](0?[1-9]|1[0-2])(?=/|$)")

_PUBLISHED_LABEL = re.compile(
    r"(?i)\b(?:first\s+published|published|posted|released|release\s+date|publication\s+date"
    r"|date\s+published|date\s+of\s+publication|issued|date\s+issued)\b"
)
_UPDATED_LABEL = re.compile(r"(?i)\b(?:last\s+)?(?:updated?|modified|reviewed|revised)\b")
_LABEL_WINDOW = 45  # characters after a label in which its date must start


def _make_date(year: int, month: int, day: int, latest: date) -> date | None:
    """Return the date if it is real, from 2000 on, and not after `latest`."""
    try:
        value = date(year, month, day)
    except ValueError:
        return None
    return value if date(2000, 1, 1) <= value <= latest else None


def _dates_in(text: str, latest: date) -> list[tuple[int, date]]:
    """Find every valid date written in `text`, as (position, date) in reading order."""
    found: list[tuple[int, date]] = []
    for match in _DAY_MONTH_YEAR.finditer(text):
        day, month, year = match.groups()
        value = _make_date(int(year), _MONTHS[month.lower()], int(day), latest)
        if value:
            found.append((match.start(), value))
    for match in _MONTH_DAY_YEAR.finditer(text):
        month, day, year = match.groups()
        value = _make_date(int(year), _MONTHS[month.lower()], int(day), latest)
        if value:
            found.append((match.start(), value))
    for match in _ISO.finditer(text):
        year, month, day = match.groups()
        value = _make_date(int(year), int(month), int(day), latest)
        if value:
            found.append((match.start(), value))
    for match in _DOTTED.finditer(text):
        day, month, year = match.groups()
        value = _make_date(int(year), int(month), int(day), latest)
        if value:
            found.append((match.start(), value))
    return sorted(found)


def _after_label(text: str, label: re.Pattern[str], latest: date) -> date | None:
    """Return the first date that starts shortly after a label such as "Published"."""
    for match in label.finditer(text):
        window = text[match.end() : match.end() + _LABEL_WINDOW]
        dates = _dates_in(window, latest)
        if dates:
            return dates[0][1]
    return None


def _url_date(url: str, latest: date) -> date | None:
    """Return a full date written in the URL path."""
    path = urlparse(url).path
    for match in _URL_FULL.finditer(path):
        year, month, day = match.groups()
        value = _make_date(int(year), int(month), int(day), latest)
        if value:
            return value
    for match in _URL_COMPACT.finditer(path):
        year, month, day = match.groups()
        value = _make_date(int(year), int(month), int(day), latest)
        if value:
            return value
    return None


def extract_date(url: str, text: str, latest: date) -> PublicationDate | None:
    """Derive a source's publication date from its URL and cleaned text.

    Rules, strongest first; the first that yields a date wins:
      1. `url_date`: a full date in the URL path (2025-04-24, 2025/04/24, 20250424).
      2. `url_month`: only the year and month are in the URL (/2025/04/ or /2025-04/).
         If the text has a full date in that same month it is used instead
         (`text_in_url_month`). The URL beats any date label in the text, because a
         label may be quoting some other document.
      3. `label_published`: a date right after "Published", "Posted", "Released", ...
      4. `label_updated`: a date right after "Updated", "Last modified", ...
      5. `text_head`: the first date near the top of the text.

    Dates after `latest` are ignored: they are events or deadlines, not publication
    dates. Returns None when no rule applies.
    """
    value = _url_date(url, latest)
    if value:
        return PublicationDate(value=value, rule="url_date")

    scan = text[:_LABEL_SCAN_CHARS]
    month_match = _URL_MONTH.search(urlparse(url).path)
    if month_match:
        year, month = int(month_match.group(1)), int(month_match.group(2))
        for _, found in _dates_in(scan, latest):
            if (found.year, found.month) == (year, month):
                return PublicationDate(value=found, rule="text_in_url_month")
        if date(year, month, 1) <= latest:
            return PublicationDate(value=date(year, month, 1), rule="url_month", precision="month")

    value = _after_label(scan, _PUBLISHED_LABEL, latest)
    if value:
        return PublicationDate(value=value, rule="label_published")

    value = _after_label(scan, _UPDATED_LABEL, latest)
    if value:
        return PublicationDate(value=value, rule="label_updated")

    head_dates = _dates_in(text[:_HEAD_CHARS], latest)
    if head_dates:
        return PublicationDate(value=head_dates[0][1], rule="text_head")
    return None


def is_recent(published: PublicationDate | None, cutoff: date) -> bool:
    """Return True if the source was published on or after `cutoff`.

    A month-only date counts as recent only if its whole month is after the cutoff's
    month: inside the cutoff month the day is unknown, so the source is excluded.
    """
    if published is None:
        return False
    if published.precision == "month":
        return (published.value.year, published.value.month) > (cutoff.year, cutoff.month)
    return published.value >= cutoff


# --- Pipeline -----------------------------------------------------------------------


def prepare_sources(sources: list[Source], latest: date) -> list[PreparedSource]:
    """Clean every source's text and derive its publication date."""
    prepared: list[PreparedSource] = []
    for source in sources:
        cleaned = clean_text(source.text)
        prepared.append(
            PreparedSource(
                source=source,
                clean_text=cleaned,
                published=extract_date(source.url, cleaned, latest),
            )
        )
    return prepared


def select_usable(prepared: list[PreparedSource], cutoff: date) -> list[PreparedSource]:
    """Keep sources that are recent enough (M4) and have enough text to use (S10)."""
    return [
        item
        for item in prepared
        if is_recent(item.published, cutoff) and len(item.clean_text) >= MIN_CLEAN_CHARS
    ]
