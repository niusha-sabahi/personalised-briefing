"""The metadata strip's wording (meta.js), run with Node: the file has no DOM access.

Skipped when Node is missing, unless REQUIRE_BROWSER is set (as CI does for the browser tests).
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from briefing.api import STATIC_DIR

SCRIPT = """
const meta = require(process.argv[1]);
const input = JSON.parse(process.argv[2]);
console.log(JSON.stringify({
  describe: meta.describe(input, "en-GB", "UTC"),
  range: meta.monthRange(input.sources.map((s) => s.published), "en-GB"),
}));
"""


@pytest.fixture(scope="module")
def node() -> str:
    path = shutil.which("node")
    if path is None:
        message = "Node is not installed"
        if os.environ.get("REQUIRE_BROWSER"):
            pytest.fail(message)
        pytest.skip(message)
    return path


def run(node: str, briefing: dict) -> dict:  # type: ignore[type-arg]
    module = Path(STATIC_DIR / "meta.js").resolve()
    result = subprocess.run(
        [node, "-e", SCRIPT, str(module), json.dumps(briefing)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    )
    return json.loads(result.stdout)  # type: ignore[no-any-return]


def sources(*dates: str | None) -> list[dict]:  # type: ignore[type-arg]
    return [{"number": n, "published": d} for n, d in enumerate(dates, start=1)]


def test_the_strip_counts_sources_dates_them_by_month_and_says_when_it_was_made(node: str) -> None:
    briefing = {
        "sources": sources("2025-04-12", "2025-05-05", None),
        "generated_at": "2026-11-08T14:32:10.123456Z",
    }
    assert run(node, briefing)["describe"] == [
        "3 sources",
        "Sources from April 2025 to May 2025",
        "Prepared 8 Nov 2026, 14:32",
    ]


def test_one_source_and_one_month_are_worded_in_the_singular(node: str) -> None:
    briefing = {"sources": sources("2025-05-01"), "generated_at": "2026-11-08T09:05:00Z"}
    assert run(node, briefing)["describe"][:2] == ["1 source", "Sources from May 2025"]


def test_the_range_works_across_a_year_and_ignores_missing_dates(node: str) -> None:
    result = run(node, {"sources": sources("2025-01-02", None, "2024-12-30", "bad")})
    assert result["range"] == "December 2024 to January 2025"


def test_a_month_is_not_shifted_by_the_time_zone(node: str) -> None:
    # 1 May is the first day of a month-only date; a local-time conversion could show April.
    assert run(node, {"sources": sources("2025-05-01")})["range"] == "May 2025"


def test_parts_that_cannot_be_worked_out_are_left_out(node: str) -> None:
    assert run(node, {"sources": []})["describe"] == []
    undated = run(node, {"sources": sources(None, None), "generated_at": "not a date"})
    assert undated["describe"] == ["2 sources"]
    assert undated["range"] is None


# --- the persona cards ------------------------------------------------------------------------


def call(node: str, function: str, *args: object) -> object:
    script = (
        "const m = require(process.argv[1]);"
        f"console.log(JSON.stringify(m.{function}(...JSON.parse(process.argv[2]))));"
    )
    module = Path(STATIC_DIR / "meta.js").resolve()
    result = subprocess.run(
        [node, "-e", script, str(module), json.dumps(list(args))],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Healthcare Policy Analyst", "HP"),
        ("Tech Startup Founder", "TS"),
        ("Forecaster", "F"),
        ("  spaced   out  words ", "SO"),
        ("", ""),
    ],
)
def test_a_card_badge_shows_the_first_letters_of_the_first_two_words(
    node: str, text: str, expected: str
) -> None:
    assert call(node, "initials", text) == expected


def test_a_card_folds_topics_beyond_the_limit_into_a_more_chip(node: str) -> None:
    six = ["a", "b", "c", "d", "e", "f"]
    assert call(node, "visibleChips", six, 4) == {
        "shown": ["a", "b", "c", "d"],
        "hidden": ["e", "f"],
    }


def test_a_single_extra_topic_is_shown_instead_of_a_plus_one_chip(node: str) -> None:
    five = ["a", "b", "c", "d", "e"]
    assert call(node, "visibleChips", five, 4) == {"shown": five, "hidden": []}
    assert call(node, "visibleChips", [], 4) == {"shown": [], "hidden": []}
