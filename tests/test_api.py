import logging
import re
from collections.abc import Callable
from pathlib import Path

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

from briefing.api import create_app, mask_secrets
from briefing.config import Settings
from briefing.generation import GenerationError
from briefing.models import BriefingDraft
from briefing.topics import TaxonomyError
from conftest import EchoGenerator, KeywordEmbedder


class Env:
    """A test app plus the fakes behind it, so tests can count calls."""

    def __init__(self, settings: Settings, generator: object | None = None) -> None:
        self.embedder = KeywordEmbedder()
        self.generator = generator or EchoGenerator()
        app = create_app(settings, embedder=self.embedder, generator=self.generator)  # type: ignore[arg-type]
        self.client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def env(settings: Settings) -> Env:
    return Env(settings)


# --- health, taxonomy ----------------------------------------------------------------------


def test_health(env: Env) -> None:
    response = env.client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_topics_returns_the_taxonomy(env: Env) -> None:
    topics = env.client.get("/topics").json()
    assert [t["id"] for t in topics] == ["health", "startups", "weather"]
    assert set(topics[0]) == {"id", "label", "description"}


def test_personas_are_listed_with_their_topics(env: Env) -> None:
    personas = {p["id"]: p for p in env.client.get("/personas").json()}
    assert personas["analyst"]["topic_ids"] == ["health"]
    assert personas["founder"]["location"] == "London"


# --- briefings -------------------------------------------------------------------------------


def test_briefing_is_markdown_by_default(env: Env) -> None:
    response = env.client.get("/briefings/analyst")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    body = response.text
    assert body.startswith("# Briefing: Health Analyst, United States")
    assert "## Health" in body and "## Sources" in body
    assert "](https://example.test/2025/04/20/health-news)" in body


def test_briefing_uses_only_recent_dated_sources_for_the_persona(env: Env) -> None:
    body = env.client.get("/briefings/analyst").text
    assert "old-health" not in body and "undated-health" not in body
    assert "startup-news" not in body


def test_briefing_as_json_lists_the_cited_sources(env: Env) -> None:
    data = env.client.get("/briefings/founder", params={"format": "json"}).json()
    assert data["persona_id"] == "founder"
    assert data["sources"] == [
        {
            "number": 1,
            "title": "Startup news",
            "url": "https://example.test/2025/05/01/startup-news",
        }
    ]
    assert data["markdown"].startswith("# Briefing: Startup Founder, London")


def test_invalid_format_is_rejected(env: Env) -> None:
    assert env.client.get("/briefings/analyst", params={"format": "pdf"}).status_code == 422


def test_unknown_persona_is_404_and_calls_nothing(env: Env) -> None:
    response = env.client.get("/briefings/nobody")
    assert response.status_code == 404
    assert "analyst" in response.json()["detail"] and "founder" in response.json()["detail"]
    assert env.generator.calls == 0  # type: ignore[attr-defined]
    assert env.embedder.calls == 0


def test_no_relevant_sources_gives_a_clear_404(env: Env) -> None:
    response = env.client.get("/briefings/forecaster")
    assert response.status_code == 404
    assert response.json() == {"detail": "No relevant recent sources were found for this persona."}
    assert env.generator.calls == 0  # type: ignore[attr-defined]


# --- caching ---------------------------------------------------------------------------------


def test_the_per_source_per_topic_limit_reaches_the_briefing(settings: Settings) -> None:
    limited = Env(settings.model_copy(update={"max_passages_per_source_per_topic": 1}))
    unlimited = Env(settings)  # the limit is off by default
    assert settings.max_passages_per_source_per_topic is None
    bullets = lambda e: e.client.get("/briefings/analyst").text.count("Finding from")  # noqa: E731
    assert (bullets(limited), bullets(unlimited)) == (1, 2)


def test_briefings_are_cached_per_persona(env: Env) -> None:
    first = env.client.get("/briefings/analyst").text
    calls = env.generator.calls  # type: ignore[attr-defined]
    assert env.client.get("/briefings/analyst").text == first
    assert env.generator.calls == calls == 1  # type: ignore[attr-defined]
    env.client.get("/briefings/founder")
    assert env.generator.calls == 2  # type: ignore[attr-defined]


def test_sources_are_embedded_once_for_all_personas(env: Env) -> None:
    env.client.get("/briefings/analyst")
    embeds_after_first = env.embedder.calls
    env.client.get("/briefings/analyst")
    assert env.embedder.calls == embeds_after_first
    env.client.get("/briefings/founder")
    # The second persona re-uses the stored tags; it only embeds its own passages and topics.
    assert env.embedder.calls < embeds_after_first * 2


class FlakyGenerator(EchoGenerator):
    """Fails on the first call, then behaves."""

    def generate(self, system: str, user: str) -> BriefingDraft:
        if self.calls == 0:
            self.calls += 1
            raise GenerationError("transient")
        return super().generate(system, user)


def test_failures_are_not_cached(settings: Settings) -> None:
    env = Env(settings, FlakyGenerator())
    assert env.client.get("/briefings/analyst").status_code == 502
    assert env.client.get("/briefings/analyst").status_code == 200


# --- error mapping (S13) -----------------------------------------------------------------------

_REQUEST = httpx.Request("POST", "https://api.openai.test/v1/responses")


def _status_error(cls: type[openai.APIStatusError], status: int) -> openai.APIStatusError:
    response = httpx.Response(status, request=_REQUEST)
    return cls("provider text with sk-leaky-secret-value", response=response, body=None)


ERRORS: list[tuple[str, Callable[[], Exception], int]] = [
    ("rate-limit", lambda: _status_error(openai.RateLimitError, 429), 503),
    ("timeout", lambda: openai.APITimeoutError(request=_REQUEST), 503),
    ("connection", lambda: openai.APIConnectionError(request=_REQUEST), 503),
    ("auth", lambda: _status_error(openai.AuthenticationError, 401), 502),
    ("permission", lambda: _status_error(openai.PermissionDeniedError, 403), 502),
    ("server", lambda: _status_error(openai.InternalServerError, 500), 502),
    ("other-openai", lambda: openai.OpenAIError("sk-leaky-secret-value"), 502),
    ("bad-answer", lambda: GenerationError("sk-leaky-secret-value"), 502),
    ("bug", lambda: RuntimeError("sk-leaky-secret-value"), 500),
]


class RaisingGenerator:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def generate(self, system: str, user: str) -> BriefingDraft:
        raise self.error


@pytest.mark.parametrize(("name", "make_error", "status"), ERRORS, ids=[e[0] for e in ERRORS])
def test_provider_failures_become_clean_json_errors(
    settings: Settings,
    name: str,
    make_error: Callable[[], Exception],
    status: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    env = Env(settings, RaisingGenerator(make_error()))
    with caplog.at_level(logging.INFO):
        response = env.client.get("/briefings/analyst")
    assert response.status_code == status
    detail = response.json()["detail"]
    assert isinstance(detail, str) and detail
    assert "sk-leaky" not in response.text and "Traceback" not in response.text
    if name != "bug":  # an unexpected bug is logged with its traceback, provider errors are not
        assert "sk-leaky" not in caplog.text


def test_debug_logging_explains_a_rejection_with_key_like_text_masked(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    message = (
        "Unsupported parameter: 'store' is not supported with this model. "
        "Key sk-proj-abc123_DEF-456 and header Bearer eyJhbGciOi.secret were echoed."
    )
    env = Env(settings, RaisingGenerator(_status_error(openai.BadRequestError, 400)))
    env.generator.error = openai.BadRequestError(  # type: ignore[attr-defined]
        message, response=httpx.Response(400, request=_REQUEST), body=None
    )
    with caplog.at_level(logging.DEBUG, logger="briefing"):
        response = env.client.get("/briefings/analyst")
    assert response.status_code == 502
    assert "Unsupported parameter: 'store'" in caplog.text  # what says what to change
    assert "sk-proj" not in caplog.text and "eyJhbGciOi" not in caplog.text
    assert "[masked]" in caplog.text
    assert "Unsupported parameter" not in response.text  # never in a response


def test_mask_secrets_leaves_ordinary_text_alone() -> None:
    assert mask_secrets("The model 'gpt-x' does not support this") == (
        "The model 'gpt-x' does not support this"
    )
    assert mask_secrets("key sk-abc, again SK-DEF.") == "key [masked], again [masked]"


# --- startup validation (S9) and docs (S20) -----------------------------------------------------


def test_invalid_taxonomy_stops_startup(settings: Settings, data_dir: Path) -> None:
    (data_dir / "personas.yaml").write_text(
        "personas:\n  - id: x\n    position: P\n    location: L\n    topic_ids: [ghost]\n",
        encoding="utf-8",
    )
    with pytest.raises(TaxonomyError, match="unknown topic id"):
        create_app(settings, embedder=KeywordEmbedder(), generator=EchoGenerator())  # type: ignore[arg-type]


def test_every_endpoint_is_documented(env: Env) -> None:
    spec = env.client.get("/openapi.json").json()
    operations = [op for path in spec["paths"].values() for op in path.values()]
    assert len(operations) == 4
    assert all(op.get("summary") for op in operations)
    briefing = spec["paths"]["/briefings/{persona_id}"]["get"]["responses"]
    assert {"200", "404", "502", "503"} <= set(briefing)


# --- logging (S15) --------------------------------------------------------------------------------


def test_generation_is_logged_without_source_text(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="briefing"):
        env.client.get("/briefings/analyst")
        env.client.get("/briefings/analyst")
    assert "Briefing for analyst generated" in caplog.text
    assert "served from memory" in caplog.text
    assert not re.search(r"Health officials said", caplog.text)


def test_the_real_data_files_build_a_working_app(settings: Settings) -> None:
    root = Path(__file__).resolve().parent.parent
    real = settings.model_copy(
        update={
            "sources_path": root / "sources_06-05-25.json",
            "topics_path": root / "topics.yaml",
            "personas_path": root / "personas.yaml",
        }
    )
    app = create_app(real, embedder=KeywordEmbedder(), generator=EchoGenerator())  # type: ignore[arg-type]
    client = TestClient(app)
    assert len(client.get("/topics").json()) == 11
    assert {p["id"] for p in client.get("/personas").json()} == {
        "healthcare-policy-analyst",
        "tech-founder",
    }
