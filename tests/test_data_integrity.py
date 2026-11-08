"""Integrity checks over the real input file (S18). Offline: no API key is needed."""

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from briefing.config import DEFAULT_CUTOFF_DATE, DEFAULT_LATEST_DATE
from briefing.sources import (
    MIN_CLEAN_CHARS,
    is_recent,
    load_sources,
    prepare_sources,
    select_usable,
)

DATA_FILE = Path(__file__).resolve().parent.parent / "sources_06-05-25.json"
# The input must not change by accident (it is protected, and this checks the content too).
# Line endings are normalised so a Windows checkout with CRLF conversion still matches.
DATA_SHA256 = "82f9efa1b103a19cf2c9d03b298af2b87f6c95a6b951ab9aee9493ca47c24ed0"


@pytest.fixture(scope="module")
def usable():  # type: ignore[no-untyped-def]
    prepared = prepare_sources(load_sources(DATA_FILE), DEFAULT_LATEST_DATE)
    return select_usable(prepared, DEFAULT_CUTOFF_DATE)


def test_the_input_file_is_the_one_the_project_was_built_on() -> None:
    content = DATA_FILE.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(content).hexdigest() == DATA_SHA256


def test_the_input_has_the_expected_shape() -> None:
    entries = json.loads(DATA_FILE.read_text(encoding="utf-8"))["reference_by_id"]
    assert len(entries) == 273
    assert {e["source_type"] for e in entries.values()} == {"web_results"}
    assert all({"url", "title", "description", "text"} <= set(e) for e in entries.values())


def test_loading_removes_the_duplicate_urls_and_keeps_every_url_once() -> None:
    sources = load_sources(DATA_FILE)
    urls = [s.url for s in sources]
    assert len(urls) == len(set(urls)) == 268
    assert all(url.startswith(("http://", "https://")) for url in urls)


def test_no_usable_source_predates_the_cutoff(usable) -> None:  # type: ignore[no-untyped-def]
    assert usable
    for item in usable:
        assert item.published is not None, item.source.url
        assert is_recent(item.published, DEFAULT_CUTOFF_DATE), item.source.url
        assert item.published.value <= DEFAULT_LATEST_DATE, item.source.url
        if item.published.precision == "day":
            assert item.published.value >= DEFAULT_CUTOFF_DATE, item.source.url
        else:
            # A month-only date is accepted only when the whole month is after the cutoff's.
            assert (item.published.value.year, item.published.value.month) > (
                DEFAULT_CUTOFF_DATE.year,
                DEFAULT_CUTOFF_DATE.month,
            ), item.source.url


def test_no_undated_or_old_source_is_usable(usable) -> None:  # type: ignore[no-untyped-def]
    prepared = prepare_sources(load_sources(DATA_FILE), DEFAULT_LATEST_DATE)
    usable_urls = {item.source.url for item in usable}
    for item in prepared:
        if item.source.url in usable_urls:
            continue
        # Everything left out is undated, too old, or too short to use.
        assert (
            item.published is None
            or not is_recent(item.published, DEFAULT_CUTOFF_DATE)
            or len(item.clean_text) < MIN_CLEAN_CHARS
        ), item.source.url


def test_every_usable_source_has_text_to_work_with(usable) -> None:  # type: ignore[no-untyped-def]
    assert all(len(item.clean_text) >= MIN_CLEAN_CHARS for item in usable)


def test_the_newest_source_is_the_reference_date() -> None:
    prepared = prepare_sources(load_sources(DATA_FILE), DEFAULT_LATEST_DATE)
    dates = [item.published.value for item in prepared if item.published]
    assert max(dates) <= DEFAULT_LATEST_DATE
    assert max(dates) >= date(2025, 5, 5)  # the data really does reach the last days of the window
