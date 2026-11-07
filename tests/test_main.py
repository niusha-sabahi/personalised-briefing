import json
from pathlib import Path

import pytest

from briefing.main import run

BODY = "Telehealth policy changed for Medicare patients across the United States. " * 6


def write_sources(path: Path) -> Path:
    entries = {
        "new": {"url": "https://a.example/2025/04/24/new", "title": "T", "text": BODY},
        "old": {"url": "https://a.example/2025/03/01/old", "title": "T", "text": BODY},
        "undated": {"url": "https://a.example/undated", "title": "T", "text": BODY},
    }
    path.write_text(json.dumps({"reference_by_id": entries}), encoding="utf-8")
    return path


def test_dates_command_reports_keep_and_drop(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run(["dates", "--sources", str(write_sources(tmp_path / "s.json"))])
    out = capsys.readouterr().out
    assert "KEEP  2025-04-24  url_date" in out
    assert "DROP  2025-03-01  url_date" in out
    assert "DROP  -           none" in out
    assert "3 sources, 1 kept" in out


def test_dates_command_can_filter_rows(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(["dates", "--only", "kept", "--sources", str(write_sources(tmp_path / "s.json"))])
    out = capsys.readouterr().out
    assert "KEEP" in out and "DROP" not in out


def test_dates_command_exits_with_an_error_for_a_bad_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        run(["dates", "--sources", str(tmp_path / "missing.json")])
    assert exit_info.value.code == 1
    assert "Cannot load sources" in capsys.readouterr().err
