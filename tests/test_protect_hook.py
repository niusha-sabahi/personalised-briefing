"""Tests for the PreToolUse protect hook, run as the harness runs it (JSON on stdin)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "protect_files.py"
BLOCK, ALLOW = 2, 0
CO_AUTHOR = "Co-Authored-By: Claude <noreply@anthropic.com>"


def run_hook(tool: str, **tool_input: str) -> int:
    payload = json.dumps({"tool_name": tool, "tool_input": tool_input})
    result = subprocess.run(
        [sys.executable, "-I", str(HOOK)], input=payload, capture_output=True, text=True
    )
    return result.returncode


@pytest.mark.parametrize(
    ("tool", "tool_input", "expected"),
    [
        # File tools: protected names are blocked in any directory, case-insensitively.
        ("Edit", {"file_path": "C:/p/.env"}, BLOCK),
        ("Write", {"file_path": "C:/p/sub/.ENV"}, BLOCK),
        ("Write", {"file_path": "C:/p/task.md"}, BLOCK),
        ("Edit", {"file_path": "C:/p/sources_06-05-25.json"}, BLOCK),
        ("NotebookEdit", {"notebook_path": "C:/p/task.md"}, BLOCK),
        ("Write", {"file_path": "C:/p/.env.example"}, ALLOW),
        ("Write", {"file_path": "C:/p/mytask.md"}, ALLOW),
        ("Write", {"file_path": "C:/p/README.md"}, ALLOW),
        # Shell: modifying a protected file is blocked.
        ("Bash", {"command": "rm .env"}, BLOCK),
        ("Bash", {"command": "echo x >> task.md"}, BLOCK),
        ("Bash", {"command": "sed -i s/a/b/ task.md"}, BLOCK),
        ("Bash", {"command": "cp .env .env.bak"}, BLOCK),
        ("Bash", {"command": "cp .env.example .env"}, BLOCK),
        ("Bash", {"command": 'bash -c "echo x > task.md"'}, BLOCK),
        ("PowerShell", {"command": "Remove-Item .env"}, BLOCK),
        ("PowerShell", {"command": "Set-Content task.md 'x'"}, BLOCK),
        # Shell: reading non-secret protected files is fine, and so is anything unrelated.
        ("Bash", {"command": "cat task.md"}, ALLOW),
        ("Bash", {"command": "rm -rf .venv"}, ALLOW),
        ("Bash", {"command": "uv run pytest"}, ALLOW),
        # .env.example is a placeholder, not .env.
        ("Bash", {"command": "cat > .env.example"}, ALLOW),
        ("PowerShell", {"command": "Set-Content .env.example 'x'"}, ALLOW),
        # Commit-message prose is ignored; code hidden in or around it is not.
        ("Bash", {"command": f'git commit -m "Add .env.example\n\n{CO_AUTHOR}"'}, ALLOW),
        (
            "Bash",
            {"command": f"git commit -m \"$(cat <<'EOF'\nmove task.md\n{CO_AUTHOR}\nEOF\n)\""},
            ALLOW,
        ),
        ("Bash", {"command": 'git commit -m "x $(rm task.md)"'}, BLOCK),
        ("Bash", {"command": 'git commit -m "ok" && rm task.md'}, BLOCK),
        # Secrets: the Read and Grep tools may not open .env or .env.* (not placeholders).
        ("Read", {"file_path": "C:/p/.env"}, BLOCK),
        ("Read", {"file_path": "C:/p/.env.local"}, BLOCK),
        ("Grep", {"pattern": "KEY", "path": "C:/p/.env"}, BLOCK),
        ("Read", {"file_path": "C:/p/.env.example"}, ALLOW),
        ("Read", {"file_path": "C:/p/task.md"}, ALLOW),
        ("Grep", {"pattern": "KEY", "path": "C:/p/src"}, ALLOW),
        # Secrets: shell commands may not read .env values...
        ("Bash", {"command": "cat .env"}, BLOCK),
        ("Bash", {"command": "grep KEY .env"}, BLOCK),
        ("Bash", {"command": "sed -n 1p .env"}, BLOCK),
        ("Bash", {"command": "python -c \"print(open('.env').read())\""}, BLOCK),
        ("PowerShell", {"command": "Get-Content .env"}, BLOCK),
        ("PowerShell", {"command": "Select-String KEY .env"}, BLOCK),
        # ...but listing names, or testing that a key exists, is allowed.
        ("Bash", {"command": "grep -oE '^[A-Za-z_]+' .env"}, ALLOW),
        ("Bash", {"command": "grep -c OPENAI_API_KEY .env"}, ALLOW),
        ("Bash", {"command": "grep -q OPENAI_API_KEY .env"}, ALLOW),
        ("Bash", {"command": "cat .env.example"}, ALLOW),
        # The names-only form cannot be chained into a real read.
        ("Bash", {"command": "grep -oE '^[A-Za-z_]+' .env; cat .env"}, BLOCK),
        ("Bash", {"command": "grep -c KEY .env | cat"}, BLOCK),
        # Secrets: printing secret environment variables is blocked, using them is not.
        ("Bash", {"command": "printenv"}, BLOCK),
        ("Bash", {"command": "env"}, BLOCK),
        ("Bash", {"command": "echo $OPENAI_API_KEY"}, BLOCK),
        ("PowerShell", {"command": "Get-ChildItem Env:"}, BLOCK),
        ("PowerShell", {"command": "Write-Host $env:OPENAI_API_KEY"}, BLOCK),
        ("Bash", {"command": 'curl -H "Authorization: Bearer $OPENAI_API_KEY" https://x'}, ALLOW),
        ("Bash", {"command": "echo $HOME"}, ALLOW),
        # Other tools are not inspected.
        ("Glob", {"pattern": "**/.env"}, ALLOW),
    ],
)
def test_hook_decision(tool: str, tool_input: dict[str, str], expected: int) -> None:
    assert run_hook(tool, **tool_input) == expected


@pytest.mark.parametrize("stdin", ["not json", ""])
def test_hook_fails_closed_on_bad_input(stdin: str) -> None:
    result = subprocess.run(
        [sys.executable, "-I", str(HOOK)], input=stdin, capture_output=True, text=True
    )
    assert result.returncode == BLOCK
