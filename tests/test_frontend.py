import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from briefing.api import STATIC_DIR, create_app
from briefing.config import Settings
from conftest import EchoGenerator, KeywordEmbedder

# The vendored libraries are third-party code committed to the repo. Pinning their hashes
# means they can only change on purpose: update these with the version in the README.
VENDORED = {
    "marked.umd.js": "b82b9334406d8bdd16b6236c08de1cb65b2a859873ca9503d9cc0b292ca3c12a",
    "purify.min.js": "cd37898f9782adf54820c413191b5691803f0f137c799d6edcfd38523b4c2c31",
}


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app(settings, embedder=KeywordEmbedder(), generator=EchoGenerator())  # type: ignore[arg-type]
    return TestClient(app)


class PageInspector(HTMLParser):
    """Collects what a Content-Security-Policy of 'self' would object to."""

    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[dict[str, str | None]] = []
        self.inline_script_text = False
        self.style_tags = 0
        self.bad_attributes: list[str] = []
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        names = {name for name, _ in attrs}
        self.bad_attributes += [n for n in names if n.startswith("on") or n == "style"]
        if tag == "style":
            self.style_tags += 1
        if tag == "script":
            self.scripts.append(dict(attrs))
            self._in_script = True

    def handle_data(self, data: str) -> None:
        if self._in_script and data.strip():
            self.inline_script_text = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_script = False


# --- the page ---------------------------------------------------------------------------------


def test_root_serves_the_page_with_security_headers(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    # The browser tab shows the same name as the banner heading.
    assert "<title>Executive Briefing</title>" in response.text
    # A banner at the top holds the title and a one-line description of the tool.
    banner = re.search(r'<header class="banner">(.*?)</header>', response.text, re.DOTALL)
    assert banner and "<h1>Executive Briefing</h1>" in banner.group(1)
    assert "every claim sourced" in banner.group(1)
    assert '<p class="prompt" id="personas-label">Select a persona:</p>' in response.text
    csp = response.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp and "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_page_has_no_inline_script_style_or_handlers(client: TestClient) -> None:
    inspector = PageInspector()
    inspector.feed(client.get("/").text)
    assert inspector.style_tags == 0 and not inspector.inline_script_text
    assert inspector.bad_attributes == []
    assert [s.get("src") for s in inspector.scripts] == [
        "/static/vendor/marked.umd.js",
        "/static/vendor/purify.min.js",
        "/static/render.js",
        "/static/meta.js",
        "/static/app.js",
    ]


def test_every_asset_the_page_loads_is_served_with_the_right_type(client: TestClient) -> None:
    assert "/static/style.css" in client.get("/").text
    expected = {
        "/static/style.css": "text/css",
        "/static/app.js": "text/javascript",
        "/static/render.js": "text/javascript",
        "/static/meta.js": "text/javascript",
        "/static/vendor/marked.umd.js": "text/javascript",
        "/static/vendor/purify.min.js": "text/javascript",
    }
    for path, content_type in expected.items():
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["content-type"].startswith(content_type), path
        assert response.headers["x-content-type-options"] == "nosniff"


def test_the_tab_icon_is_served_from_the_app_itself(client: TestClient) -> None:
    page = client.get("/").text
    assert '<link rel="icon" type="image/svg+xml" href="/static/favicon.svg">' in page
    response = client.get("/static/favicon.svg")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    # An icon is an image: it must carry no script or external reference.
    body = response.text.lower()
    assert "<script" not in body and "onload" not in body and "href" not in body
    assert body.count("http") == 1  # only the SVG namespace


def test_the_page_and_its_assets_are_revalidated_on_every_load(client: TestClient) -> None:
    for path in ("/", "/static/style.css", "/static/favicon.svg"):
        assert client.get(path).headers["cache-control"] == "no-cache", path
    assert "cache-control" not in client.get("/health").headers


def test_api_and_docs_are_not_given_the_page_policy(client: TestClient) -> None:
    assert "content-security-policy" not in client.get("/health").headers
    assert client.get("/docs").status_code == 200
    assert "content-security-policy" not in client.get("/docs").headers


def test_the_page_is_not_part_of_the_api_reference(client: TestClient) -> None:
    assert "/" not in client.get("/openapi.json").json()["paths"]


def test_page_talks_only_to_the_apis_json_endpoints() -> None:
    source = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert '"/personas"' in source and '"/topics"' in source and "?format=json" in source
    assert "innerHTML" in source  # only for sanitised briefing HTML
    assert source.count("innerHTML") == 1


def test_the_personas_are_a_radio_group_that_can_be_used_from_the_keyboard(
    client: TestClient,
) -> None:
    assert '<div id="personas" role="radiogroup" aria-labelledby="personas-label">' in (
        client.get("/").text
    )
    source = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert '"role", "radio"' in source and "aria-checked" in source
    assert "aria-pressed" not in source
    for key in ("ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp", "Home", "End"):
        assert key in source, key
    # The arrow keys must only move focus: choosing a persona starts a (paid) briefing.
    move = source[source.index("function moveFocus") : source.index("async function showBriefing")]
    assert "showBriefing" not in move and ".click(" not in move


def test_nothing_but_the_sanitised_briefing_is_inserted_as_html() -> None:
    for name in ("app.js", "meta.js"):
        source = (STATIC_DIR / name).read_text(encoding="utf-8")
        for sink in ("outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            assert sink not in source, (name, sink)
    # The strip, the persona cards and the status line are built from text, never from markup.
    assert "innerHTML" not in (STATIC_DIR / "meta.js").read_text(encoding="utf-8")


def test_the_page_has_a_metadata_strip_and_a_logo(client: TestClient) -> None:
    page = client.get("/").text
    assert '<p id="meta" class="meta" hidden></p>' in page
    assert '<img class="logo" src="/static/favicon.svg" alt=""' in page  # decorative: empty alt


def test_the_stylesheet_covers_printing_and_reduced_motion() -> None:
    css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
    assert "@media print" in css and "attr(href)" in css  # links are spelled out on paper
    assert "prefers-reduced-motion" in css  # the spinner stops for people who ask
    assert "@import" not in css and "url(http" not in css  # nothing from another site


# --- vendored libraries ---------------------------------------------------------------------------


@pytest.mark.parametrize(("name", "digest"), VENDORED.items())
def test_vendored_libraries_are_unchanged(name: str, digest: str) -> None:
    content = (STATIC_DIR / "vendor" / name).read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(content).hexdigest() == digest


def test_vendored_libraries_ship_their_licences() -> None:
    vendor = Path(STATIC_DIR / "vendor")
    assert (vendor / "LICENSE-marked").read_text(encoding="utf-8").startswith("# License")
    assert "Apache License" in (vendor / "LICENSE-dompurify").read_text(encoding="utf-8")
