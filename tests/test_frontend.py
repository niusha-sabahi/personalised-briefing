import hashlib
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
    assert "Personalised Briefing" in response.text
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
        "/static/app.js",
    ]


def test_every_asset_the_page_loads_is_served_with_the_right_type(client: TestClient) -> None:
    assert "/static/style.css" in client.get("/").text
    expected = {
        "/static/style.css": "text/css",
        "/static/app.js": "text/javascript",
        "/static/render.js": "text/javascript",
        "/static/vendor/marked.umd.js": "text/javascript",
        "/static/vendor/purify.min.js": "text/javascript",
    }
    for path, content_type in expected.items():
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["content-type"].startswith(content_type), path
        assert response.headers["x-content-type-options"] == "nosniff"


def test_api_and_docs_are_not_given_the_page_policy(client: TestClient) -> None:
    assert "content-security-policy" not in client.get("/health").headers
    assert client.get("/docs").status_code == 200
    assert "content-security-policy" not in client.get("/docs").headers


def test_the_page_is_not_part_of_the_api_reference(client: TestClient) -> None:
    assert "/" not in client.get("/openapi.json").json()["paths"]


def test_page_talks_only_to_the_apis_json_endpoints() -> None:
    source = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert '"/personas"' in source and "?format=json" in source
    assert "innerHTML" in source  # only for sanitised briefing HTML
    assert source.count("innerHTML") == 1


# --- vendored libraries ---------------------------------------------------------------------------


@pytest.mark.parametrize(("name", "digest"), VENDORED.items())
def test_vendored_libraries_are_unchanged(name: str, digest: str) -> None:
    content = (STATIC_DIR / "vendor" / name).read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(content).hexdigest() == digest


def test_vendored_libraries_ship_their_licences() -> None:
    vendor = Path(STATIC_DIR / "vendor")
    assert (vendor / "LICENSE-marked").read_text(encoding="utf-8").startswith("# License")
    assert "Apache License" in (vendor / "LICENSE-dompurify").read_text(encoding="utf-8")
