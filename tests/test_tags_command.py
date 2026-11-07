from collections.abc import Sequence
from pathlib import Path

import openai
import pytest

from briefing.main import run

ROOT = Path(__file__).resolve().parent.parent


def _configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # keeps a developer's real settings file out of the test
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    monkeypatch.setenv("GENERATION_MODEL", "gen-model")
    monkeypatch.setenv("EMBEDDING_MODEL", "embed-model")
    monkeypatch.setenv("SOURCES_PATH", str(ROOT / "sources_06-05-25.json"))
    monkeypatch.setenv("TOPICS_PATH", str(ROOT / "topics.yaml"))
    monkeypatch.setenv("PERSONAS_PATH", str(ROOT / "personas.yaml"))
    monkeypatch.setenv("CACHE_PATH", str(tmp_path / "cache"))


def test_tags_command_needs_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("OPENAI_API_KEY", "GENERATION_MODEL", "EMBEDDING_MODEL"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit) as exit_info:
        run(["tags"])
    assert exit_info.value.code == 1
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_tags_command_hides_provider_error_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _configure(monkeypatch, tmp_path)

    class Failing:
        hits = misses = 0

        def embed(self, texts: Sequence[str]) -> list[list[float]]:
            raise openai.OpenAIError("Incorrect API key provided: sk-leaky-value")

    monkeypatch.setattr("briefing.main._build_embedder", lambda settings: Failing())
    with pytest.raises(SystemExit) as exit_info:
        run(["tags"])
    err = capsys.readouterr().err
    assert exit_info.value.code == 1
    assert "OpenAIError" in err and "sk-leaky-value" not in err


def test_tags_command_prints_report_and_cache_counts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _configure(monkeypatch, tmp_path)

    class Hashed:
        hits, misses = 3, 7

        def embed(self, texts: Sequence[str]) -> list[list[float]]:
            return [[1.0 + len(t) % 5, 1.0 + len(t) % 3, 1.0] for t in texts]

    monkeypatch.setattr("briefing.main._build_embedder", lambda settings: Hashed())
    run(["tags", "--threshold", "0.9"])
    out = capsys.readouterr().out
    assert "At threshold 0.90" in out
    assert "Embeddings: 7 requested from OpenAI, 3 from cache." in out
