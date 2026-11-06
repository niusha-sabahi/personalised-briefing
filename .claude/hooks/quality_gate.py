"""Stop hook: run format, lint, type check and the test suite before the agent may stop.

Exit code 2 blocks the stop and feeds the failure output back to the agent, so it
must fix the problem. Exit code 0 lets it stop.

Safeguards:
  - Does nothing until the project has a pyproject.toml and at least one test.
  - Gives up after MAX_ATTEMPTS consecutive failures in a session (so an unfixable
    problem cannot trap the agent in a loop) and shows the user a warning instead.
  - Skips tests marked `integration`, which need the live OpenAI API.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_ATTEMPTS = 3
STEP_TIMEOUT_SECONDS = 240
MAX_REPORT_CHARS = 6000

# (label, uv arguments, exit codes that count as success)
STEPS: list[tuple[str, list[str], set[int]]] = [
    ("ruff format", ["run", "ruff", "format"], {0}),
    ("ruff check", ["run", "ruff", "check", "--fix"], {0}),
    ("mypy", ["run", "mypy", "src"], {0}),
    # pytest exits 5 when no tests were collected, which is not a failure here.
    ("pytest", ["run", "pytest", "-q", "-m", "not integration"], {0, 5}),
]


def uv_command() -> list[str]:
    """Return the command that runs uv (uv may be installed only as a Python module)."""
    uv = shutil.which("uv")
    return [uv] if uv else [sys.executable, "-m", "uv"]


def has_tests(project: Path) -> bool:
    """Return True if the project has at least one test file."""
    tests = project / "tests"
    return tests.is_dir() and any(tests.glob("test_*.py"))


def attempts_file(session_id: str) -> Path:
    """Return the temp file that counts consecutive failures for this session."""
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_") or "default"
    return Path(tempfile.gettempdir()) / f"briefing_quality_gate_{safe}.count"


def run_steps(project: Path) -> list[str]:
    """Run every step and return a report for each one that failed."""
    failures: list[str] = []
    for label, args, ok_codes in STEPS:
        try:
            result = subprocess.run(
                [*uv_command(), *args],
                cwd=project,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=STEP_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            failures.append(f"## {label}: timed out after {STEP_TIMEOUT_SECONDS}s")
            continue
        if result.returncode not in ok_codes:
            output = (result.stdout + result.stderr).strip()
            failures.append(f"## {label} failed (exit {result.returncode})\n{output}")
    return failures


def main() -> int:
    """Run the quality gate for one Stop event read from stdin."""
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        data = {}

    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    if not (project / "pyproject.toml").is_file() or not has_tests(project):
        return 0

    counter = attempts_file(str(data.get("session_id", "")))
    failures = run_steps(project)

    if not failures:
        counter.unlink(missing_ok=True)
        return 0

    attempts = int(counter.read_text()) + 1 if counter.exists() else 1
    report = "\n\n".join(failures)
    if len(report) > MAX_REPORT_CHARS:
        report = report[:MAX_REPORT_CHARS] + "\n... (output truncated)"

    if attempts >= MAX_ATTEMPTS:
        counter.unlink(missing_ok=True)
        warning = f"Quality gate still failing after {attempts} attempts; not blocking.\n\n{report}"
        print(json.dumps({"systemMessage": warning}))
        return 0

    counter.write_text(str(attempts))
    print(
        f"Quality gate failed (attempt {attempts} of {MAX_ATTEMPTS}). Fix these, then finish:\n\n"
        f"{report}",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
