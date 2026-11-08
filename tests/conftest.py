"""Shared fixtures: a tiny corpus, taxonomy and fake models, so API tests need no key."""

import json
import re
from collections.abc import Sequence
from pathlib import Path

import pytest

from briefing.config import Settings
from briefing.models import BriefingDraft, DraftBullet, DraftSection

TOPICS_YAML = """\
topics:
  - id: health
    label: Health
    description: health health health health health health
  - id: startups
    label: Startups
    description: startup startup startup startup startup
  - id: weather
    label: Weather
    description: weather weather weather weather weather weather
"""

PERSONAS_YAML = """\
personas:
  - id: analyst
    position: Health Analyst
    location: United States
    topic_ids: [health]
  - id: founder
    position: Startup Founder
    location: London
    topic_ids: [startups]
  - id: forecaster
    position: Forecaster
    location: Nowhere
    topic_ids: [weather]
"""

HEALTH_TEXT = "\n\n".join(
    ["Health officials said health coverage and health spending rose again this spring. " * 3] * 2
)
STARTUP_TEXT = "\n\n".join(
    ["A startup raised money and the startup market is busy this spring, one startup said. " * 3]
    * 2
)


def _entry(url: str, title: str, text: str) -> dict[str, str]:
    return {
        "source_type": "web_results",
        "url": url,
        "title": title,
        "description": "",
        "text": text,
    }


SOURCES = {
    "1": _entry("https://example.test/2025/04/20/health-news", "Health news", HEALTH_TEXT),
    "2": _entry("https://example.test/2025/05/01/startup-news", "Startup news", STARTUP_TEXT),
    # Too old (before the 2025-04-06 cutoff) and undated: both must be excluded.
    "3": _entry("https://example.test/2025/01/10/old-health", "Old health news", HEALTH_TEXT),
    "4": _entry("https://example.test/undated-health", "Undated health", HEALTH_TEXT),
}


class KeywordEmbedder:
    """Vector = counts of 'health', 'startup' and 'weather' (offset so none is zero)."""

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        words = ("health", "startup", "weather")
        return [[t.lower().count(w) + 0.01 for w in words] for t in texts]


class EchoGenerator:
    """Writes one bullet per passage in the prompt, citing it under the passage's topic."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, system: str, user: str) -> BriefingDraft:
        self.calls += 1
        found = re.findall(r'<passage id="([^"]+)" topic="([^"]+)">', user)
        sections: dict[str, list[DraftBullet]] = {}
        for passage_id, topic_id in found:
            bullet = DraftBullet(text=f"Finding from {passage_id}.", passage_ids=[passage_id])
            sections.setdefault(topic_id, []).append(bullet)
        return BriefingDraft(
            sections=[DraftSection(topic_id=t, bullets=b) for t, b in sections.items()]
        )


@pytest.fixture(autouse=True)
def _isolate_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear every setting from the environment, so a developer's values cannot affect a test."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    (tmp_path / "topics.yaml").write_text(TOPICS_YAML, encoding="utf-8")
    (tmp_path / "personas.yaml").write_text(PERSONAS_YAML, encoding="utf-8")
    (tmp_path / "sources.json").write_text(json.dumps({"reference_by_id": SOURCES}), "utf-8")
    return tmp_path


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> Path:
    """Point the command-line tools at the tiny corpus through the environment."""
    monkeypatch.chdir(data_dir)  # keeps a developer's real settings file out of the test
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    monkeypatch.setenv("GENERATION_MODEL", "gen-model")
    monkeypatch.setenv("EMBEDDING_MODEL", "embed-model")
    monkeypatch.setenv("SOURCES_PATH", str(data_dir / "sources.json"))
    monkeypatch.setenv("TOPICS_PATH", str(data_dir / "topics.yaml"))
    monkeypatch.setenv("PERSONAS_PATH", str(data_dir / "personas.yaml"))
    return data_dir


@pytest.fixture
def settings(data_dir: Path) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        openai_api_key="sk-test-secret",  # type: ignore[arg-type]
        generation_model="gen-model",
        embedding_model="embed-model",
        sources_path=data_dir / "sources.json",
        topics_path=data_dir / "topics.yaml",
        personas_path=data_dir / "personas.yaml",
        cache_path=data_dir / "cache",
        tagging_threshold=0.9,
        passage_threshold=0.9,
        top_k=5,
    )
