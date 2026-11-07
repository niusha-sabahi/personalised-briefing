from pathlib import Path
from typing import Any

import pytest

from briefing.config import Settings
from briefing.main import run
from briefing.service import make_openai_client


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> Path:
    monkeypatch.chdir(data_dir)  # keeps a developer's real settings file out of the test
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    monkeypatch.setenv("GENERATION_MODEL", "gen-model")
    monkeypatch.setenv("EMBEDDING_MODEL", "embed-model")
    monkeypatch.setenv("SOURCES_PATH", str(data_dir / "sources.json"))
    monkeypatch.setenv("TOPICS_PATH", str(data_dir / "topics.yaml"))
    monkeypatch.setenv("PERSONAS_PATH", str(data_dir / "personas.yaml"))
    return data_dir


def test_serve_starts_the_app_factory(configured: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr("briefing.main.uvicorn.run", lambda *a, **k: started.append((a, k)))
    run([])
    run(["serve"])
    assert (
        started
        == [(("briefing.api:create_app",), {"factory": True, "host": "127.0.0.1", "port": 8000})]
        * 2
    )


def test_serve_needs_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("OPENAI_API_KEY", "GENERATION_MODEL", "EMBEDDING_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("briefing.main.uvicorn.run", lambda *a, **k: pytest.fail("started"))
    with pytest.raises(SystemExit) as exit_info:
        run(["serve"])
    assert exit_info.value.code == 1
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_invalid_setting_values_are_never_echoed(
    configured: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TAGGING_THRESHOLD", "sk-not-a-number")
    with pytest.raises(SystemExit):
        run(["serve"])
    err = capsys.readouterr().err
    assert "TAGGING_THRESHOLD" in err and "sk-not-a-number" not in err


def test_serve_refuses_an_invalid_taxonomy(
    configured: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (configured / "personas.yaml").write_text(
        "personas:\n  - id: x\n    position: P\n    location: L\n    topic_ids: [ghost]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("briefing.main.uvicorn.run", lambda *a, **k: pytest.fail("started"))
    with pytest.raises(SystemExit) as exit_info:
        run(["serve"])
    assert exit_info.value.code == 1
    assert "unknown topic id" in capsys.readouterr().err


def test_openai_client_uses_the_configured_timeout_and_retries(settings: Settings) -> None:
    custom = settings.model_copy(update={"openai_timeout_seconds": 12.0, "openai_max_retries": 5})
    client = make_openai_client(custom)
    assert client.max_retries == 5 and client.timeout == 12.0


def test_log_level_is_normalised_and_validated(settings: Settings) -> None:
    assert (
        Settings.model_validate({**settings.model_dump(), "log_level": "debug"}).log_level
        == "DEBUG"
    )
    with pytest.raises(ValueError, match="unknown log level"):
        Settings.model_validate({**settings.model_dump(), "log_level": "loud"})
