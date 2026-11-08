from pathlib import Path

import pytest

from briefing.config import Settings
from briefing.main import run
from briefing.models import Persona, PreparedSource, Source, Topic
from briefing.reports import passages_report
from briefing.retrieval import TaggedSource, tag_corpus
from briefing.sources import load_sources, prepare_sources, select_usable
from briefing.tagging import Tag
from briefing.topics import load_taxonomy
from conftest import KeywordEmbedder


class CountingEmbedder(KeywordEmbedder):
    """KeywordEmbedder with the counters the command prints."""

    hits = 3
    misses = 4


@pytest.fixture
def usable(settings: Settings) -> list[PreparedSource]:
    prepared = prepare_sources(load_sources(settings.sources_path), settings.latest_date)
    return select_usable(prepared, settings.cutoff_date)


def report_for(
    settings: Settings, usable: list[PreparedSource], persona_id: str, threshold: float
) -> str:
    taxonomy = load_taxonomy(settings.topics_path, settings.personas_path)
    persona = taxonomy.persona(persona_id)
    assert isinstance(persona, Persona)
    topics: list[Topic] = [t for t in taxonomy.topics if t.id in persona.topic_ids]
    embedder = KeywordEmbedder()
    tagged = tag_corpus(usable, taxonomy.topics, embedder, 0.9, 4)
    return passages_report(
        tagged,
        persona,
        topics,
        embedder,
        top_k=5,
        per_topic_min=1,
        threshold=threshold,
        per_topic=3,
        per_source=3,
    )


def test_report_lists_selected_sources_with_chosen_passages(
    settings: Settings, usable: list[PreparedSource]
) -> None:
    report = report_for(settings, usable, "analyst", threshold=0.9)
    assert report.startswith("analyst (Health Analyst, United States)")
    assert "1 sources selected (top_k 5, per-topic minimum 1)" in report
    assert "up to 3 per topic and 3 per source" in report
    assert "2 passages chosen from 1 of 1 selected sources" in report
    assert "[1] Health news" in report and "tags: health" in report
    assert "2 passages, 0 dropped as boilerplate, 2 chosen" in report
    assert "* health" in report
    assert "Startup news" not in report


def test_report_shows_each_topics_passages_at_every_threshold(
    settings: Settings, usable: list[PreparedSource]
) -> None:
    report = report_for(settings, usable, "analyst", threshold=0.9)
    header = next(line for line in report.splitlines() if line.strip().startswith("topic"))
    assert all(f"{value:.2f}" in header for value in (0.30, 0.35, 0.40, 0.45, 0.50))
    assert header.rstrip().endswith("chosen")
    row = next(line for line in report.splitlines() if line.strip().startswith("health "))
    assert row.split()[1:] == ["2", "2", "2", "2", "2", "2"]  # 5 thresholds, then chosen


def test_report_says_when_nothing_clears_the_threshold(
    settings: Settings, usable: list[PreparedSource]
) -> None:
    report = report_for(settings, usable, "analyst", threshold=1.5)
    assert "0 passages chosen from 0 of 1 selected sources" in report
    assert "* health" not in report and "0 chosen" in report


def test_persona_with_no_candidates_has_an_empty_report(
    settings: Settings, usable: list[PreparedSource]
) -> None:
    report = report_for(settings, usable, "forecaster", threshold=0.5)
    assert "0 sources selected" in report
    assert "0 passages chosen from 0 of 0 selected sources" in report


def test_report_counts_dropped_boilerplate(settings: Settings) -> None:
    text = f"{'health ' * 40}\n\n{'health ' * 40}This site uses cookies. Read our privacy policy."
    source = Source(id="1", url="https://x.test/a", title="A page", description="", text=text)
    item = PreparedSource(source=source, clean_text=text, published=None)
    taxonomy = load_taxonomy(settings.topics_path, settings.personas_path)
    persona = taxonomy.persona("analyst")
    assert isinstance(persona, Persona)
    health = taxonomy.topic("health")
    assert isinstance(health, Topic)
    report = passages_report(
        [TaggedSource(item, (Tag("health", 0.9),))],
        persona,
        [health],
        KeywordEmbedder(),
        top_k=5,
        per_topic_min=1,
        threshold=0.9,
        per_topic=3,
        per_source=3,
    )
    assert "2 passages, 1 dropped as boilerplate, 1 chosen" in report


# --- the command ----------------------------------------------------------------------------


def test_passages_command_reports_one_persona(
    configured: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("briefing.main._build_embedder", lambda settings: CountingEmbedder())
    run(["passages", "--persona", "founder"])
    out = capsys.readouterr().out
    assert "founder (Startup Founder, London)" in out and "analyst (" not in out
    assert "Startup news" in out
    assert "Embeddings: 4 requested from OpenAI, 3 from cache." in out


def test_passages_command_uses_the_configured_per_source_per_topic_limit(
    configured: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MAX_PASSAGES_PER_SOURCE_PER_TOPIC", "1")
    monkeypatch.setattr("briefing.main._build_embedder", lambda settings: CountingEmbedder())
    run(["passages", "--persona", "analyst", "--threshold", "0.9"])
    out = capsys.readouterr().out
    assert "(1 per source per topic)" in out
    assert "1 passages chosen from 1 of 1 selected sources" in out


def test_passages_command_defaults_to_every_persona(
    configured: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("briefing.main._build_embedder", lambda settings: CountingEmbedder())
    run(["passages", "--threshold", "0.99"])
    out = capsys.readouterr().out
    for persona in ("analyst (", "founder (", "forecaster ("):
        assert persona in out
    assert "passage threshold 0.99" in out


def test_passages_command_rejects_an_unknown_persona(
    configured: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("briefing.main._build_embedder", lambda settings: CountingEmbedder())
    with pytest.raises(SystemExit) as exit_info:
        run(["passages", "--persona", "nobody"])
    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert "Unknown persona 'nobody'" in err and "analyst" in err
