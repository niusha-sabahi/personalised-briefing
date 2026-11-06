import pytest

from briefing.config import Settings


def _set_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    monkeypatch.setenv("GENERATION_MODEL", "gen-model")
    monkeypatch.setenv("EMBEDDING_MODEL", "embed-model")


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    settings = Settings(_env_file=None)
    assert settings.generation_model == "gen-model"
    assert settings.embedding_model == "embed-model"
    assert settings.tagging_threshold == 0.35


def test_api_key_is_not_leaked_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    assert "sk-test-secret" not in repr(Settings(_env_file=None))
