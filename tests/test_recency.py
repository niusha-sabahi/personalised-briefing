"""The recency preference: passages that state a date inside the window rank higher (M4, M8)."""

import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from briefing.api import create_app
from briefing.config import Settings
from briefing.main import run
from briefing.models import Persona, PreparedSource, Source, Topic
from briefing.reports import passages_report
from briefing.retrieval import (
    PassageCandidate,
    SelectedSource,
    TaggedSource,
    build_context,
    choose_passages,
    gather_candidates,
)
from briefing.sources import dates_in_text
from briefing.tagging import Tag
from conftest import EchoGenerator, KeywordEmbedder

WINDOW = (date(2025, 4, 6), date(2025, 5, 6))
PLAIN = "Health officials said health coverage and health spending rose again this spring. " * 3
DATED = "On April 20, 2025 " + PLAIN  # the same keywords, so the same score as PLAIN
OLD = "On January 5, 2025 " + PLAIN
TOPICS = [Topic(id="health", label="Health", description="health health health health health")]


def prepared(url: str, text: str, title: str = "A page") -> PreparedSource:
    source = Source(id=url, url=url, title=title, description="", text=text)
    return PreparedSource(source=source, clean_text=text, published=None)


def selected(text: str) -> SelectedSource:
    return SelectedSource(prepared("https://x.test/a", text), (Tag("health", 0.9),))


# --- finding dates in text ------------------------------------------------------------------


def test_dates_in_text_finds_each_full_date_in_reading_order() -> None:
    text = "Published April 20, 2025; updated 3 May 2025; archived 2025-04-30."
    assert dates_in_text(text, date(2025, 5, 6)) == [
        date(2025, 4, 20),
        date(2025, 5, 3),
        date(2025, 4, 30),
    ]


def test_dates_after_the_latest_are_events_and_are_ignored() -> None:
    assert dates_in_text("The hearing is on June 10, 2025.", date(2025, 5, 6)) == []
    assert dates_in_text("Nothing is dated here.", date(2025, 5, 6)) == []


# --- marking passages as recent ---------------------------------------------------------------


def test_a_passage_is_recent_when_it_states_a_date_inside_the_window() -> None:
    text = "\n\n".join([DATED, OLD, PLAIN])
    found = gather_candidates([selected(text)], TOPICS, KeywordEmbedder(), WINDOW)
    assert [c.recent for c in found] == [True, False, False]


def test_nothing_is_recent_without_a_window() -> None:
    found = gather_candidates([selected(DATED)], TOPICS, KeywordEmbedder())
    assert [c.recent for c in found] == [False]


def test_the_window_includes_both_of_its_end_dates() -> None:
    first = PLAIN.replace("Health", "On April 6, 2025 health")
    last = PLAIN.replace("Health", "On May 6, 2025 health")
    found = gather_candidates([selected(f"{first}\n\n{last}")], TOPICS, KeywordEmbedder(), WINDOW)
    assert [c.recent for c in found] == [True, True]


# --- ranking with the bonus ---------------------------------------------------------------------


def candidate(position: int, score: float, recent: bool) -> PassageCandidate:
    return PassageCandidate(0, position, f"text {position}", (score,), recent)


def picked(
    candidates: Sequence[PassageCandidate], bonus: float, threshold: float = 0.4
) -> list[int]:
    chosen = choose_passages(candidates, ["a"], threshold, 1, 9, None, bonus)
    return [p.candidate.position for p in chosen]


def test_a_dated_passage_beats_a_better_scoring_evergreen_one_when_the_bonus_is_enough() -> None:
    candidates = [candidate(0, 0.45, True), candidate(1, 0.60, False)]
    assert picked(candidates, bonus=0.0) == [1]
    assert picked(candidates, bonus=0.10) == [1]  # 0.55 is still below 0.60
    assert picked(candidates, bonus=0.20) == [0]


def test_the_bonus_never_lets_a_passage_below_the_threshold_in() -> None:
    assert picked([candidate(0, 0.39, True)], bonus=0.5) == []


def test_the_reported_score_is_the_real_similarity_not_the_boosted_one() -> None:
    chosen = choose_passages([candidate(0, 0.45, True)], ["a"], 0.4, 1, 9, None, 0.2)
    assert chosen[0].score == 0.45


def test_the_bonus_does_not_change_the_order_of_undated_passages() -> None:
    candidates = [candidate(0, 0.5, False), candidate(1, 0.6, False), candidate(2, 0.55, False)]
    assert picked(candidates, bonus=0.0) == picked(candidates, bonus=0.3) == [1]


# --- wiring ------------------------------------------------------------------------------


def test_build_context_prefers_the_dated_passage_when_given_a_window_and_a_bonus() -> None:
    text = f"{PLAIN}\n\n{DATED}"
    source = [selected(text)]
    args = (source, TOPICS, KeywordEmbedder(), 0.9, 1, 5)
    without = build_context(*args)
    with_bonus = build_context(*args, recent_window=WINDOW, recency_bonus=0.15)
    assert "April 20, 2025" not in without.passages[0].text  # a tie goes to document order
    assert "April 20, 2025" in with_bonus.passages[0].text


def test_the_report_marks_dated_passages_and_counts_them() -> None:
    item = prepared("https://x.test/a", f"{PLAIN}\n\n{DATED}")
    persona = Persona(id="p", position="Analyst", location="Nowhere", topic_ids=("health",))
    report = passages_report(
        [TaggedSource(item, (Tag("health", 0.9),))],
        persona,
        TOPICS,
        KeywordEmbedder(),
        top_k=5,
        per_topic_min=1,
        threshold=0.9,
        per_topic=1,
        per_source=5,
        recent_window=WINDOW,
        recency_bonus=0.15,
    )
    assert "recency bonus 0.15" in report
    assert "1 of the chosen passages state a date inside the recency window (D)" in report
    assert " D * health" in report


def test_the_report_header_omits_the_bonus_when_it_is_off() -> None:
    item = prepared("https://x.test/a", PLAIN)
    persona = Persona(id="p", position="Analyst", location="Nowhere", topic_ids=("health",))
    report = passages_report(
        [TaggedSource(item, (Tag("health", 0.9),))],
        persona,
        TOPICS,
        KeywordEmbedder(),
        top_k=5,
        per_topic_min=1,
        threshold=0.9,
        per_topic=1,
        per_source=5,
    )
    assert "recency bonus" not in report
    assert "0 of the chosen passages state a date" in report


class CountingEmbedder(KeywordEmbedder):
    hits = misses = 0


def test_passages_command_uses_the_configured_bonus_and_can_override_it(
    configured: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("briefing.main._build_embedder", lambda settings: CountingEmbedder())
    run(["passages", "--persona", "analyst", "--threshold", "0.9"])
    assert "recency bonus 0.15" in capsys.readouterr().out
    run(["passages", "--persona", "analyst", "--threshold", "0.9", "--recency-bonus", "0.3"])
    assert "recency bonus 0.30" in capsys.readouterr().out
    run(["passages", "--persona", "analyst", "--threshold", "0.9", "--recency-bonus", "0"])
    assert "recency bonus" not in capsys.readouterr().out


class RecordingGenerator(EchoGenerator):
    """Remembers the last prompt it was given."""

    prompt = ""

    def generate(self, system: str, user: str):  # type: ignore[no-untyped-def]
        self.prompt = user
        return super().generate(system, user)


def test_the_bonus_reaches_the_briefing_through_the_service(
    settings: Settings, data_dir: Path
) -> None:
    entry = {
        "source_type": "web_results",
        "url": "https://example.test/2025/04/20/mixed",
        "title": "Mixed health news",
        "description": "",
        "text": f"{PLAIN}\n\n{DATED}",
    }
    (data_dir / "mixed.json").write_text(json.dumps({"reference_by_id": {"1": entry}}), "utf-8")

    def prompt_with(bonus: float) -> str:
        changed = settings.model_copy(
            update={
                "sources_path": data_dir / "mixed.json",
                "max_passages_per_topic": 1,
                "recency_bonus": bonus,
            }
        )
        generator = RecordingGenerator()
        app = create_app(changed, embedder=KeywordEmbedder(), generator=generator)  # type: ignore[arg-type]
        assert TestClient(app).get("/briefings/analyst").status_code == 200
        return generator.prompt

    assert "April 20, 2025" not in prompt_with(0.0)
    assert "April 20, 2025" in prompt_with(0.15)


def test_the_default_bonus_is_the_calibrated_one(settings: Settings) -> None:
    assert settings.recency_bonus == 0.15
