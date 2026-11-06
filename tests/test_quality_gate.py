"""Tests for the Stop-hook quality gate (steps are replaced so no real tools run)."""

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

GATE = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "quality_gate.py"
PASS_STEP = ("ok", ["run", "python", "-c", "pass"], {0})
FAIL_STEP = ("bad", ["run", "python", "-c", "import sys; print('boom'); sys.exit(1)"], {0})


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("quality_gate", GATE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # A throwaway project that satisfies the "has pyproject and tests" check.
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(module, "uv_command", lambda: [sys.executable, "-c", "pass", "--"])
    # Counter files go to a per-test temp dir.
    monkeypatch.setattr(module.tempfile, "gettempdir", lambda: str(tmp_path))
    return module


def run_main(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch, steps: list[tuple[str, list[str], set[int]]]
) -> int:
    monkeypatch.setattr(gate, "STEPS", steps)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"session_id": "s1"})))
    return int(gate.main())


def test_noop_without_pyproject(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "pyproject.toml").unlink()
    assert run_main(gate, monkeypatch, [FAIL_STEP]) == 0


def test_noop_without_tests(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "tests" / "test_x.py").unlink()
    assert run_main(gate, monkeypatch, [FAIL_STEP]) == 0


def test_passes_when_all_steps_pass(gate: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    assert run_main(gate, monkeypatch, [PASS_STEP]) == 0


def test_blocks_on_failure_and_reports_output(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The stand-in uv command ignores the real arguments, so use a failing command directly.
    monkeypatch.setattr(
        gate,
        "uv_command",
        lambda: [sys.executable, "-c", "print('boom'); raise SystemExit(1)", "--"],
    )
    assert run_main(gate, monkeypatch, [("bad", ["x"], {0})]) == 2
    assert "bad failed" in capsys.readouterr().err


def test_gives_up_after_max_attempts(gate: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gate, "uv_command", lambda: [sys.executable, "-c", "raise SystemExit(1)", "--"]
    )
    steps = [("bad", ["x"], {0})]
    results = [run_main(gate, monkeypatch, steps) for _ in range(gate.MAX_ATTEMPTS)]
    assert results == [2] * (gate.MAX_ATTEMPTS - 1) + [0]


def test_success_resets_attempt_counter(gate: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gate, "uv_command", lambda: [sys.executable, "-c", "raise SystemExit(1)", "--"]
    )
    assert run_main(gate, monkeypatch, [("bad", ["x"], {0})]) == 2
    monkeypatch.setattr(gate, "uv_command", lambda: [sys.executable, "-c", "pass", "--"])
    assert run_main(gate, monkeypatch, [("ok", ["x"], {0})]) == 0
    monkeypatch.setattr(
        gate, "uv_command", lambda: [sys.executable, "-c", "raise SystemExit(1)", "--"]
    )
    assert run_main(gate, monkeypatch, [("bad", ["x"], {0})]) == 2
