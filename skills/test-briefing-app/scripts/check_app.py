"""Check a running briefing server: its endpoints, security headers and the briefings it writes.

Standard library only, so it runs with any Python 3.10+. Exit code 0 means every check passed.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_URL = "http://127.0.0.1:8000"
_LINK = re.compile(r"\]\((https?://[^)\s]+)\)")
_SOURCE_LINE = re.compile(r"^(\d+)\. \[.*\]\((https?://[^)\s]+)\)$")


def fetch(base_url: str, path: str, timeout: float = 30) -> tuple[int, dict[str, str], bytes]:
    """GET `path` and return the status, lower-cased headers and body (HTTP errors included)."""
    try:
        with urllib.request.urlopen(base_url + path, timeout=timeout) as response:  # noqa: S310
            status, headers, body = response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        status, headers, body = error.code, error.headers, error.read()
    return status, {k.lower(): v for k, v in headers.items()}, body


def check_briefing(persona: dict, labels: dict[str, str], data: dict) -> list[str]:
    """Return the problems found in one briefing (empty when it is valid).

    Args:
        persona: The persona object from `/personas`.
        labels: Topic label by topic id, from `/topics`.
        data: The `/briefings/{id}?format=json` response.
    """
    problems: list[str] = []
    markdown = data.get("markdown", "")
    sources = data.get("sources", [])
    allowed = {label for topic_id, label in labels.items() if topic_id in persona["topic_ids"]}

    if data.get("persona_id") != persona["id"]:
        problems.append(f"persona_id is {data.get('persona_id')!r}, expected {persona['id']!r}")
    title = f"# Briefing: {persona['position']}, {persona['location']}"
    if not markdown.startswith(title):
        problems.append(f"does not start with {title!r}")

    headings = re.findall(r"^## (.+)$", markdown, flags=re.MULTILINE)
    sections = [h for h in headings if h != "Sources"]
    if "Sources" not in headings:
        problems.append("no 'Sources' section")
    if not sections:
        problems.append("no topic section")
    for heading in sections:
        if heading not in allowed:
            problems.append(f"section {heading!r} is not one of the persona's topics")

    bullets = [line for line in markdown.splitlines() if line.startswith("- ")]
    if not bullets:
        problems.append("no bullets")
    problems += [
        f"bullet without a source link: {b[:60]!r}" for b in bullets if not _LINK.search(b)
    ]

    listed = [m for line in markdown.splitlines() if (m := _SOURCE_LINE.match(line))]
    listed_urls = [m.group(2) for m in listed]
    if [int(m.group(1)) for m in listed] != list(range(1, len(listed) + 1)):
        problems.append("the Sources list is not numbered 1, 2, 3, ...")
    if listed_urls != [s["url"] for s in sources]:
        problems.append("the Sources list does not match the 'sources' field")
    if not sources:
        problems.append("no sources")
    elif any(s["number"] != n for n, s in enumerate(sources, start=1)):
        problems.append("'sources' numbers are not 1, 2, 3, ...")
    problems += [
        f"link to a URL that is not a listed source: {url}"
        for url in dict.fromkeys(_LINK.findall(markdown))
        if url not in listed_urls
    ]
    return problems


def check_server(base_url: str, persona_ids: list[str], timeout: float) -> list[str]:
    """Run every check against the server and return the failures, printing each result."""
    failures: list[str] = []

    def record(name: str, problems: list[str]) -> None:
        print(f"{'PASS' if not problems else 'FAIL'}  {name}")
        for problem in problems:
            print(f"      - {problem}")
            failures.append(f"{name}: {problem}")

    status, _, body = fetch(base_url, "/health")
    record("GET /health", [] if status == 200 and b"ok" in body else [f"status {status}"])

    status, _, body = fetch(base_url, "/topics")
    topics = json.loads(body) if status == 200 else []
    record("GET /topics", [] if topics else [f"status {status} or empty list"])
    status, _, body = fetch(base_url, "/personas")
    personas = json.loads(body) if status == 200 else []
    record("GET /personas", [] if personas else [f"status {status} or empty list"])

    status, headers, _ = fetch(base_url, "/")
    problems = [] if status == 200 else [f"status {status}"]
    if "'self'" not in headers.get("content-security-policy", ""):
        problems.append("missing Content-Security-Policy")
    if headers.get("x-content-type-options") != "nosniff":
        problems.append("missing X-Content-Type-Options: nosniff")
    record("GET / (web page and security headers)", problems)

    status, _, _ = fetch(base_url, "/briefings/no-such-persona")
    record("unknown persona gives 404", [] if status == 404 else [f"status {status}"])

    labels = {t["id"]: t["label"] for t in topics}
    wanted = [p for p in personas if not persona_ids or p["id"] in persona_ids]
    for missing in set(persona_ids) - {p["id"] for p in personas}:
        record(f"persona {missing}", ["not served by this app"])
    for persona in wanted:
        name = f"GET /briefings/{persona['id']}?format=json"
        started = time.monotonic()
        status, _, body = fetch(base_url, f"/briefings/{persona['id']}?format=json", timeout)
        if status != 200:
            record(name, [f"status {status}: {body[:200].decode('utf-8', 'replace')}"])
            continue
        data = json.loads(body)
        record(
            f"{name} ({time.monotonic() - started:.0f} s)", check_briefing(persona, labels, data)
        )
        status, _, plain = fetch(base_url, f"/briefings/{persona['id']}", timeout)
        same = plain.decode("utf-8") == data["markdown"]
        record(
            f"GET /briefings/{persona['id']} (Markdown)",
            [] if status == 200 and same else ["differs from the JSON briefing"],
        )
    return failures


def wait_for_health(base_url: str, seconds: float) -> bool:
    """Poll `/health` until it answers or the time is up."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if fetch(base_url, "/health", 2)[0] == 200:
                return True
        except OSError:
            pass
        time.sleep(0.5)
    return False


def stop(process: subprocess.Popen) -> None:
    """Stop the server and its child processes."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
    else:
        process.terminate()
    process.wait(timeout=15)


def main(argv: list[str] | None = None) -> int:
    """Parse the options, optionally start the server, run the checks and return an exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url", default=DEFAULT_URL, help=f"server address (default {DEFAULT_URL})"
    )
    parser.add_argument("--start", action="store_true", help="start `uv run briefing` first")
    parser.add_argument("--persona", action="append", default=[], help="check only this persona")
    parser.add_argument("--timeout", type=float, default=120, help="seconds per briefing")
    args = parser.parse_args(argv)

    process = None
    if args.start:
        process = subprocess.Popen(
            ["uv", "run", "briefing"],
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    try:
        if not wait_for_health(args.url, 60 if process else 3):
            print(f"FAIL  no server answered at {args.url}; start it with `uv run briefing`")
            return 1
        failures = check_server(args.url, args.persona, args.timeout)
    finally:
        if process:
            stop(process)
    print(f"\n{'All checks passed.' if not failures else f'{len(failures)} problem(s).'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
