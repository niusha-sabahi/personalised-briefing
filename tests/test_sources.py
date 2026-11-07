import json
from datetime import date
from pathlib import Path

import pytest

from briefing.models import PreparedSource, PublicationDate, Source
from briefing.sources import (
    MIN_CLEAN_CHARS,
    SourceDataError,
    clean_text,
    extract_date,
    is_recent,
    load_sources,
    prepare_sources,
    select_usable,
)

LATEST = date(2025, 5, 6)
CUTOFF = date(2025, 4, 6)
REAL_SOURCES = Path(__file__).resolve().parent.parent / "sources_06-05-25.json"


def write_sources(path: Path, entries: dict[str, dict[str, object]]) -> Path:
    path.write_text(json.dumps({"reference_by_id": entries}), encoding="utf-8")
    return path


def entry(url: str, text: str = "x", **extra: object) -> dict[str, object]:
    return {
        "source_type": "web_results",
        "url": url,
        "title": "T",
        "description": "D",
        "text": text,
        **extra,
    }


# --- loading -----------------------------------------------------------------------


def test_load_sorts_by_url_and_fills_missing_fields(tmp_path: Path) -> None:
    path = write_sources(
        tmp_path / "s.json",
        {
            "b": entry("https://b.example/"),
            "a": {"url": "https://a.example/", "title": None, "description": None, "text": None},
        },
    )
    loaded = load_sources(path)
    assert [s.url for s in loaded] == ["https://a.example/", "https://b.example/"]
    assert (loaded[0].title, loaded[0].description, loaded[0].text) == ("", "", "")


def test_load_keeps_longest_text_among_duplicate_urls(tmp_path: Path) -> None:
    path = write_sources(
        tmp_path / "s.json",
        {
            "id1": entry("https://x.example/", "short"),
            "id2": entry("https://x.example/", "a much longer text"),
            "id3": entry("https://x.example/", "tiny"),
        },
    )
    (only,) = load_sources(path)
    assert only.id == "id2"


def test_load_breaks_ties_by_smallest_id(tmp_path: Path) -> None:
    path = write_sources(
        tmp_path / "s.json",
        {"b": entry("https://x.example/", "same"), "a": entry("https://x.example/", "same")},
    )
    (only,) = load_sources(path)
    assert only.id == "a"


@pytest.mark.parametrize(
    "content",
    ["not json", "[]", '{"other": {}}', '{"reference_by_id": {"a": {"title": "no url"}}}'],
)
def test_load_rejects_malformed_files(tmp_path: Path, content: str) -> None:
    path = tmp_path / "s.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(SourceDataError):
        load_sources(path)


def test_load_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SourceDataError):
        load_sources(tmp_path / "missing.json")


# --- cleaning ----------------------------------------------------------------------


def test_clean_turns_links_into_anchor_text_and_drops_images() -> None:
    raw = 'The [Medicare rules](https://x.example/a "title") changed. ![logo](https://x.example/l.png)'
    assert clean_text(raw) == "The Medicare rules changed."


def test_clean_separates_links_that_touch_text() -> None:
    assert "Tong Apr 17, 2025" in clean_text("[Noah Tong](https://x.example/p)Apr 17, 2025 2:35pm")


def test_clean_drops_navigation_and_consent_lines() -> None:
    raw = "\n".join(
        [
            "- [Home](https://x.example/)",
            "- [Latest news and events](https://x.example/news)",
            "We use cookies to improve your experience. Accept all cookies.",
            "[skip to main content](https://x.example/#main)",
            "Share",
            "* * *",
            "[iframe](javascript:false)",
            "Telehealth coverage was extended through September 2025 for Medicare patients.",
        ]
    )
    assert (
        clean_text(raw)
        == "Telehealth coverage was extended through September 2025 for Medicare patients."
    )


def test_clean_keeps_headings_and_bare_dates() -> None:
    cleaned = clean_text("# Rules\n\n2025-04-24\n\nShare")
    assert cleaned == "# Rules\n\n2025-04-24"


def test_clean_keeps_a_long_sentence_that_mentions_cookies() -> None:
    sentence = (
        "Researchers studied how third-party cookies affect advertising revenue across thirty "
        "European publishers over a period of three years and reported a modest decline."
    )
    assert clean_text(sentence) == sentence


def test_clean_drops_a_multi_sentence_cookie_banner() -> None:
    banner = (
        "This site uses cookies. Visit our [cookies policy page](https://x.example/c) or click "
        "the link in any footer for more information and to change your preferences."
    )
    assert clean_text(banner) == ""


def test_clean_keeps_repeated_short_lines_once() -> None:
    assert (
        clean_text("Policy updates this week\n\nPolicy updates this week")
        == "Policy updates this week"
    )


def test_clean_strips_html_tags_and_entities() -> None:
    assert (
        clean_text("Fees rose <b>sharply</b> &amp; unexpectedly in 2025")
        == "Fees rose sharply & unexpectedly in 2025"
    )


# --- dates -------------------------------------------------------------------------


def published(url: str, text: str = "") -> PublicationDate | None:
    return extract_date(url, text, LATEST)


@pytest.mark.parametrize(
    "url",
    [
        "https://a.example/news/2025-04-24/story",
        "https://a.example/2025/04/24/story/",
        "https://a.example/docs/20250424/file.pdf",
        "https://a.example/news/story-2025-04-24_en",
    ],
)
def test_date_from_url(url: str) -> None:
    result = published(url)
    assert result == PublicationDate(value=date(2025, 4, 24), rule="url_date")


def test_url_date_wins_over_text() -> None:
    result = published("https://a.example/2025/04/24/x", "Published 1 March 2025")
    assert result is not None and result.value == date(2025, 4, 24)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Published: 24 April 2025", date(2025, 4, 24)),
        ("Published on April 24, 2025", date(2025, 4, 24)),
        ("Posted: Apr 24, 2025", date(2025, 4, 24)),
        ("Released 24th April 2025", date(2025, 4, 24)),
        ("Date published: 2025-04-24", date(2025, 4, 24)),
        ("First published 24.4.2025", date(2025, 4, 24)),
        ("Published: 9 Sept 2024", date(2024, 9, 9)),
    ],
)
def test_published_label_formats(text: str, expected: date) -> None:
    result = published("https://a.example/story", text)
    assert result == PublicationDate(value=expected, rule="label_published")


def test_published_label_beats_an_earlier_unlabelled_date() -> None:
    text = "Conference on 1 March 2025\n\nPublished: 24 April 2025"
    result = published("https://a.example/story", text)
    assert result == PublicationDate(value=date(2025, 4, 24), rule="label_published")


def test_label_needs_its_date_nearby() -> None:
    text = "Published by the ministry " + "word " * 30 + "on 24 April 2025"
    result = published("https://a.example/story", text)
    assert result is not None and result.rule == "text_head"


@pytest.mark.parametrize(
    "label", ["Last updated: ", "Updated ", "Last update\n\n", "Last modified "]
)
def test_updated_label(label: str) -> None:
    result = published("https://a.example/story", f"{label}9 April 2025")
    assert result == PublicationDate(value=date(2025, 4, 9), rule="label_updated")


def test_published_label_beats_updated_label() -> None:
    text = "Updated: 30 April 2025\n\nPublished: 2 April 2025"
    result = published("https://a.example/story", text)
    assert result == PublicationDate(value=date(2025, 4, 2), rule="label_published")


def test_first_date_near_the_top_is_the_fallback() -> None:
    result = published("https://a.example/story", "Headline\n\n24 April 2025\n\nBody. 1 June 2024")
    assert result == PublicationDate(value=date(2025, 4, 24), rule="text_head")


def test_dates_deep_in_the_text_are_not_used() -> None:
    assert published("https://a.example/story", "word " * 1000 + "24 April 2025") is None


def test_dates_after_the_latest_date_are_ignored() -> None:
    text = "Deadline: 23 September 2025\n\nPublished: 7 May 2025\n\nMeeting on 2025-06-01"
    assert published("https://a.example/story", text) is None


def test_the_latest_date_itself_is_allowed() -> None:
    result = published("https://a.example/story", "Published: 6 May 2025")
    assert result is not None and result.value == LATEST


@pytest.mark.parametrize(
    "text", ["Published: 31 April 2025", "Published: 2025-13-01", "Published 5/4/2025"]
)
def test_impossible_and_ambiguous_dates_are_ignored(text: str) -> None:
    assert published("https://a.example/story", text) is None


def test_url_month_only_uses_a_text_date_in_that_month() -> None:
    text = "Earlier note 3 March 2025\n\nUpdate on 28 April 2025"
    result = published("https://a.example/2025/04/story", text)
    assert result == PublicationDate(value=date(2025, 4, 28), rule="text_in_url_month")


def test_url_month_only_without_a_matching_text_date_has_month_precision() -> None:
    result = published("https://a.example/files/2025-05/report.pdf", "No dates here")
    assert result == PublicationDate(value=date(2025, 5, 1), rule="url_month", precision="month")


def test_url_month_beats_a_label_from_another_month() -> None:
    result = published("https://a.example/2025/04/story", "Published: 25 February 2025")
    assert result is not None and result.rule == "url_month"


def test_url_month_after_the_latest_date_is_ignored() -> None:
    assert published("https://a.example/2025/06/story", "") is None


def test_year_only_in_url_is_not_a_date() -> None:
    assert published("https://a.example/news/2025/story", "") is None


def test_no_date_anywhere() -> None:
    assert published("https://a.example/story", "Plain text with no dates.") is None


# --- recency -----------------------------------------------------------------------


def day(value: date) -> PublicationDate:
    return PublicationDate(value=value, rule="url_date")


def month(value: date) -> PublicationDate:
    return PublicationDate(value=value, rule="url_month", precision="month")


def test_cutoff_boundary() -> None:
    assert not is_recent(day(date(2025, 4, 5)), CUTOFF)
    assert is_recent(day(date(2025, 4, 6)), CUTOFF)
    assert is_recent(day(date(2025, 5, 6)), CUTOFF)


def test_undated_is_not_recent() -> None:
    assert not is_recent(None, CUTOFF)


def test_month_precision_is_recent_only_after_the_cutoff_month() -> None:
    assert is_recent(month(date(2025, 5, 1)), CUTOFF)
    assert not is_recent(month(date(2025, 4, 1)), CUTOFF)  # day unknown inside the cutoff month
    assert not is_recent(month(date(2025, 3, 1)), CUTOFF)


# --- pipeline ----------------------------------------------------------------------


def make_source(url: str, text: str) -> Source:
    return Source(id=url, url=url, title="T", description="D", text=text)


def test_prepare_cleans_text_and_dates_each_source() -> None:
    body = "A sentence about telehealth policy changes in the United States. " * 5
    source = make_source(
        "https://a.example/2025/04/24/story", f"[Menu](https://a.example/)\n\n{body}"
    )
    (item,) = prepare_sources([source], LATEST)
    assert "Menu" not in item.clean_text and item.clean_text.startswith("A sentence")
    assert item.published == PublicationDate(value=date(2025, 4, 24), rule="url_date")


def test_select_usable_applies_recency_and_minimum_length() -> None:
    long_text = "x" * MIN_CLEAN_CHARS

    def item(url: str, clean: str, when: PublicationDate | None) -> PreparedSource:
        return PreparedSource(source=make_source(url, ""), clean_text=clean, published=when)

    prepared = [
        item("keep", long_text, day(date(2025, 4, 6))),
        item("old", long_text, day(date(2025, 4, 5))),
        item("undated", long_text, None),
        item("short", "x" * (MIN_CLEAN_CHARS - 1), day(date(2025, 5, 1))),
    ]
    assert [p.source.url for p in select_usable(prepared, CUTOFF)] == ["keep"]


# --- the real data file (S18) --------------------------------------------------------


@pytest.fixture(scope="module")
def real_prepared() -> list[PreparedSource]:
    return prepare_sources(load_sources(REAL_SOURCES), LATEST)


def test_real_data_has_no_duplicate_urls(real_prepared: list[PreparedSource]) -> None:
    urls = [p.source.url for p in real_prepared]
    assert len(urls) == len(set(urls)) == 268


def test_real_data_selection_never_predates_the_cutoff(real_prepared: list[PreparedSource]) -> None:
    selected = select_usable(real_prepared, CUTOFF)
    assert len(selected) > 50
    for item in selected:
        assert item.published is not None
        assert item.published.value >= CUTOFF
        assert is_recent(item.published, CUTOFF)
        assert item.published.value <= LATEST


@pytest.mark.parametrize(
    ("url_start", "expected", "rule"),
    [
        ("https://hansard.parliament.uk/lords/2025-05-01/", date(2025, 5, 1), "url_date"),
        (
            "https://cinea.ec.europa.eu/news-events/news/life-calls-proposals-2025-claim",
            date(2025, 4, 24),
            "url_date",
        ),
        (
            "https://www.europarl.europa.eu/doceo/document/A-10-2025-0073_EN.html",
            date(2025, 4, 16),
            "text_head",
        ),
        ("https://www.medrxiv.org/content/medrxiv/early/2025/04/04/", date(2025, 4, 4), "url_date"),
    ],
)
def test_real_data_known_dates(
    real_prepared: list[PreparedSource], url_start: str, expected: date, rule: str
) -> None:
    (match,) = [p for p in real_prepared if p.source.url.startswith(url_start)]
    assert match.published is not None
    assert (match.published.value, match.published.rule) == (expected, rule)
