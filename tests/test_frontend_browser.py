"""Runs the page's real rendering code in a real headless browser (S8).

DOMPurify needs a browser DOM, so these tests start Chrome, Chromium or Edge. They skip when
none is found, unless REQUIRE_BROWSER is set (CI sets it, so a missing browser fails there
instead of silently skipping the sanitiser tests).
"""

import html
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.parse
from collections.abc import Iterator
from html.parser import HTMLParser
from pathlib import Path

import pytest
import uvicorn

from briefing.api import create_app
from briefing.config import Settings
from conftest import EchoGenerator, KeywordEmbedder

HARNESS = Path(__file__).resolve().parent / "frontend_harness" / "harness.html"
ALLOWED_TAGS = {"h1", "h2", "h3", "p", "ul", "ol", "li", "a", "strong", "em", "code", "br"}


def find_browser() -> str | None:
    """Return the path of an installed Chromium-based browser, or None."""
    names = (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "chrome",
        "msedge",
        "microsoft-edge",
    )
    found = [shutil.which(name) for name in names]
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            found += [
                os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
            ]
    found.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    return next((path for path in found if path and os.path.exists(path)), None)


@pytest.fixture(scope="session")
def browser() -> str:
    path = find_browser()
    if path is None:
        message = "No Chrome, Chromium or Edge found"
        if os.environ.get("REQUIRE_BROWSER"):
            pytest.fail(message)
        pytest.skip(message)
    return path


def dump_dom(browser: str, url: str, budget_ms: int = 5000) -> str:
    """Load `url` in a headless browser and return the page's DOM as HTML."""
    command = [browser, "--headless", "--disable-gpu", f"--virtual-time-budget={budget_ms}"]
    if os.environ.get("CI"):
        command.append("--no-sandbox")  # Chrome cannot use its sandbox inside most CI containers
    # A throwaway profile, so a browser the user has open is not disturbed.
    with tempfile.TemporaryDirectory() as profile:
        result = subprocess.run(
            [*command, f"--user-data-dir={profile}", "--dump-dom", url],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
        )
    assert result.returncode == 0, result.stderr[-500:]
    return result.stdout


def render_in_browser(browser: str, markdown_cases: list[str], unsafe: bool = False) -> list[str]:
    url = HARNESS.as_uri() + "?cases=" + urllib.parse.quote(json.dumps(markdown_cases))
    if unsafe:
        url += "&unsafe=1"
    page = dump_dom(browser, url)
    match = re.search(r'<pre id="out">(.*?)</pre>', page, re.DOTALL)
    assert match, page[-500:]
    data = json.loads(html.unescape(match.group(1)))
    assert "error" not in data, data
    assert isinstance(data["results"], list)
    return [str(item) for item in data["results"]]


class Inspector(HTMLParser):
    """Lists the tags, attributes and link targets in a piece of rendered HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.attributes: list[tuple[str, str, str | None]] = []
        self.text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self.attributes += [(tag, name, value) for name, value in attrs]

    def handle_data(self, data: str) -> None:
        self.text += data


def inspect(rendered: str) -> Inspector:
    inspector = Inspector()
    inspector.feed(rendered)
    return inspector


# (name, markdown, strings that must not survive, case-insensitive)
HOSTILE = [
    ("script", "Hello <script>alert(1)</script> world", ("<script", "alert")),
    ("img-handler", '<img src=x onerror="alert(1)">', ("<img", "onerror", "alert")),
    ("markdown-image", "![x](https://evil.test/p.png)", ("<img", "evil.test")),
    ("javascript-link", "[click](javascript:alert(1))", ("javascript:", "alert")),
    ("mixed-case-javascript", "[click](JaVaScRiPt:alert(1))", ("javascript:", "alert")),
    ("entity-javascript", '<a href="&#106;avascript:alert(1)">x</a>', ("javascript:", "alert")),
    (
        "data-link",
        "[click](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)",
        ("data:",),
    ),
    ("relative-link", "[click](/docs)", ('href="/docs"',)),
    (
        "anchor-handler",
        '<a href="https://ok.test" onclick="alert(1)" style="x:y">x</a>',
        ("onclick", "alert", "style"),
    ),
    ("iframe", '<iframe src="https://evil.test"></iframe>', ("iframe", "evil.test")),
    ("style-tag", "<style>body{display:none}</style>text", ("<style", "display")),
    ("svg-handler", '<svg onload="alert(1)"></svg>', ("<svg", "onload", "alert")),
    (
        "form",
        '<form action="https://evil.test"><input name=a></form>',
        ("<form", "<input", "evil.test"),
    ),
    ("base-tag", '<base href="https://evil.test/">', ("<base", "evil.test")),
    (
        "meta-refresh",
        '<meta http-equiv="refresh" content="0;url=https://evil.test">',
        ("<meta", "evil.test"),
    ),
    (
        "mutation-xss",
        "<math><mtext><table><mglyph><style><!--</style>"
        '<img title="--&gt;&lt;img src=1 onerror=alert(1)&gt;">',
        ("onerror", "alert", "<img"),
    ),
    ("object", '<object data="https://evil.test/x.swf"></object>', ("<object", "evil.test")),
]


def violations(forbidden: tuple[str, ...], output: str) -> list[str]:
    """List everything in rendered HTML that a safe briefing must not contain."""
    found: list[str] = [f"{f!r} survived" for f in forbidden if f.lower() in output.lower()]
    parsed = inspect(output)
    found += [f"tag <{tag}>" for tag in set(parsed.tags) - ALLOWED_TAGS]
    for tag, attribute, value in parsed.attributes:
        if tag != "a" or attribute not in {"href", "target", "rel"}:
            found.append(f"attribute {attribute} on <{tag}>")
        elif attribute == "href" and not (value and re.match(r"https?://", value)):
            found.append(f"link target {value!r}")
    return found


def test_hostile_markup_is_neutralised_by_the_real_page_code(browser: str) -> None:
    rendered = render_in_browser(browser, [markdown for _, markdown, _ in HOSTILE])
    assert len(rendered) == len(HOSTILE)
    for (name, _, forbidden), output in zip(HOSTILE, rendered, strict=True):
        assert violations(forbidden, output) == [], f"{name}: {output!r}"


def test_the_checks_do_catch_unsanitised_output(browser: str) -> None:
    # Negative control: the harness can skip DOMPurify (`unsafe`), and the same checks must
    # then flag hostile markup. This shows the test above can fail, so its pass means something.
    names = ("script", "img-handler", "markdown-image", "anchor-handler", "iframe", "form")
    chosen = [case for case in HOSTILE if case[0] in names]
    rendered = render_in_browser(browser, [markdown for _, markdown, _ in chosen], unsafe=True)
    for (name, _, forbidden), output in zip(chosen, rendered, strict=True):
        assert violations(forbidden, output), f"{name} was not flagged: {output!r}"


def test_every_link_opens_safely_whatever_the_markup_says(browser: str) -> None:
    cases = [
        "[a](https://example.test/a)",
        '<a href="https://example.test/b" target="_self" rel="opener">b</a>',
        '<a href="https://example.test/c" target="_top">c</a>',
    ]
    for output in render_in_browser(browser, cases):
        links = [(name, value) for tag, name, value in inspect(output).attributes if tag == "a"]
        assert ("target", "_blank") in links
        assert ("rel", "noopener noreferrer") in links
        assert not any(name == "rel" and value != "noopener noreferrer" for name, value in links)


def test_a_real_briefing_keeps_its_structure_and_citation_links(browser: str) -> None:
    markdown = (
        "# Briefing: Policy Analyst, United States\n\n"
        "## Telemedicine\n\n"
        "- Rule changed & coverage widened. [\\[1\\]](https://example.test/one)\n"
        "- Second point. [\\[2\\]](https://example.test/two)\n\n"
        "## Sources\n\n"
        "1. [First page](https://example.test/one)\n"
        "2. [Second page](https://example.test/two)\n"
    )
    (output,) = render_in_browser(browser, [markdown])
    found = inspect(output)
    assert found.tags.count("h1") == 1 and found.tags.count("h2") == 2
    assert found.tags.count("ul") == 1 and found.tags.count("ol") == 1
    assert found.tags.count("li") == 4
    hrefs = [value for _, name, value in found.attributes if name == "href"]
    assert hrefs == ["https://example.test/one", "https://example.test/two"] * 2
    assert "Rule changed & coverage widened." in found.text
    assert "[1]" in found.text and "[2]" in found.text


# --- the whole page, served by the app, under its Content-Security-Policy ---------------------


@pytest.fixture
def live_server(settings: Settings) -> Iterator[str]:
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
    assert server.started, "test server did not start"
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def test_the_page_runs_under_its_policy_and_lists_the_personas(
    browser: str, live_server: str
) -> None:
    page = dump_dom(browser, live_server + "/")
    buttons = re.findall(r'<button type="button" aria-pressed="false">(.*?)</button>', page)
    assert [html.unescape(b) for b in buttons] == [
        "Health Analyst · United States",
        "Startup Founder · London",
        "Forecaster · Nowhere",
    ]
