"""The Agent Skill (M15): its format, its commands, and its check script against a live server."""

import importlib.util
import re
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
import uvicorn

from briefing.api import create_app
from briefing.config import Settings
from conftest import EchoGenerator, KeywordEmbedder

SKILL_DIR = Path(__file__).resolve().parent.parent / "skills" / "test-briefing-app"
SKILL_MD = SKILL_DIR / "SKILL.md"
SCRIPT = SKILL_DIR / "scripts" / "check_app.py"


@pytest.fixture(scope="module")
def check_app() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_app", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _frontmatter() -> dict[str, str]:
    text = SKILL_MD.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n", text, flags=re.DOTALL)
    assert match, "SKILL.md must start with YAML frontmatter"
    return dict(re.findall(r"^([a-z-]+): (.+)$", match.group(1), flags=re.MULTILINE))


# --- the format (agentskills.io) -----------------------------------------------------------


def test_the_frontmatter_follows_the_skill_format() -> None:
    meta = _frontmatter()
    assert meta["name"] == SKILL_DIR.name  # the name must match the folder
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", meta["name"]) and len(meta["name"]) <= 64
    assert 50 <= len(meta["description"]) <= 1024
    assert len(meta.get("compatibility", "")) <= 500


def test_the_skill_is_agent_neutral() -> None:
    text = SKILL_MD.read_text(encoding="utf-8") + SCRIPT.read_text(encoding="utf-8")
    for word in ("claude", "anthropic", "cursor", "copilot", "codex"):
        assert word not in text.lower(), word


def test_the_skill_stays_small_enough_to_load() -> None:
    assert len(SKILL_MD.read_text(encoding="utf-8").splitlines()) < 500


def test_the_commands_it_names_exist() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    for path in re.findall(r"uv run python (\S+\.py)", text):
        assert (SKILL_DIR.parent.parent / path).is_file(), path
    commands = re.findall(r"`?(uv run briefing[^\n`]*)", text)
    assert "uv run briefing topics" in commands
    assert all(c.startswith("uv run briefing") for c in commands)
    for option in re.findall(r"`(--[a-z-]+)", text):
        assert option in SCRIPT.read_text(encoding="utf-8"), option


# --- check_briefing ------------------------------------------------------------------------

PERSONA = {"id": "p", "position": "Analyst", "location": "US", "topic_ids": ["health"]}
LABELS = {"health": "Health", "other": "Other"}
GOOD = (
    "# Briefing: Analyst, US\n\n## Health\n\n"
    "- A finding. [\\[1\\]](https://a.test/x)\n\n"
    "## Sources\n\n1. [Title](https://a.test/x)\n"
)


def _data(markdown: str = GOOD, sources: list[dict] | None = None) -> dict:
    listed = [{"number": 1, "title": "Title", "url": "https://a.test/x"}]
    return {"persona_id": "p", "markdown": markdown, "sources": sources or listed}


def test_a_valid_briefing_has_no_problems(check_app: ModuleType) -> None:
    assert check_app.check_briefing(PERSONA, LABELS, _data()) == []


@pytest.mark.parametrize(
    ("markdown", "expected"),
    [
        (GOOD.replace("# Briefing: Analyst, US", "# Something else"), "does not start with"),
        (GOOD.replace("## Health", "## Other"), "not one of the persona's topics"),
        (GOOD.replace(" [\\[1\\]](https://a.test/x)", ""), "bullet without a source link"),
        (GOOD.replace("- A finding.", "- A finding [x](https://evil.test/y)."), "not a listed"),
        (GOOD.replace("## Sources", "## Refs"), "no 'Sources' section"),
        (GOOD.replace("1. [Title]", "2. [Title]"), "not numbered"),
    ],
)
def test_each_defect_is_reported(check_app: ModuleType, markdown: str, expected: str) -> None:
    problems = check_app.check_briefing(PERSONA, LABELS, _data(markdown))
    assert any(expected in p for p in problems), problems


def test_a_sources_field_that_disagrees_is_reported(check_app: ModuleType) -> None:
    other = [{"number": 1, "title": "T", "url": "https://b.test/z"}]
    problems = check_app.check_briefing(PERSONA, LABELS, _data(sources=other))
    assert any("does not match" in p for p in problems)


# --- the script against a live server ------------------------------------------------------


@pytest.fixture
def server_url(settings: Settings) -> Iterator[str]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    app = create_app(settings, embedder=KeywordEmbedder(), generator=EchoGenerator())  # type: ignore[arg-type]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def test_the_script_passes_against_a_healthy_server(
    check_app: ModuleType, server_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code = check_app.main(["--url", server_url, "--persona", "analyst", "--persona", "founder"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "FAIL" not in out and "All checks passed" in out
    assert "GET /briefings/analyst?format=json" in out and "GET /briefings/founder" in out


def test_the_script_fails_when_a_persona_cannot_be_briefed(
    check_app: ModuleType, server_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # The forecaster's only topic matches no recent source, so the app answers 404.
    code = check_app.main(["--url", server_url, "--persona", "forecaster"])
    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL  GET /briefings/forecaster?format=json" in out and "status 404" in out


def test_the_script_fails_for_an_unknown_persona(
    check_app: ModuleType, server_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert check_app.main(["--url", server_url, "--persona", "nobody"]) == 1
    assert "not served by this app" in capsys.readouterr().out


def test_the_script_reports_when_no_server_is_running(
    check_app: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert check_app.main(["--url", f"http://127.0.0.1:{port}"]) == 1
    assert "no server answered" in capsys.readouterr().out
