"""PreToolUse hook: block edits to, and deletion of, the protected project files.

Reads the tool call as JSON on stdin. Exit code 2 blocks the call and shows
stderr to the agent. Any other exit code lets the call through.

Protected:
  - by filename:  .env, sources_06-05-25.json, task.md
  - by path:      .claude/settings.json, .claude/settings.local.json,
                  everything under .claude/hooks/ (this hook included)

File tools (Edit/Write/NotebookEdit) are blocked outright for protected files.
Shell tools (Bash/PowerShell) are blocked when the command names a protected
file together with a modifying or deleting operation. Read-only use (cat, grep,
head, loading the JSON in code) is allowed. Shell matching is best-effort.
"""

import json
import re
import sys

# Matched on the exact file name, in any directory.
PROTECTED_NAMES = (".env", "sources_06-05-25.json", "task.md")

# Matched on the normalised path (forward slashes, lower case).
# TO ALLOW EDITS TO THE HOOK/SETTINGS FILES AGAIN: replace the whole tuple below
# (the lines from "PROTECTED_PATHS = (" to the closing ")") with: PROTECTED_PATHS = ()
# Do NOT delete the PROTECTED_PATHS name itself, or the script raises NameError.
# Also remove the matching deny rules in .claude/settings.json (see CLAUDE.md).
PROTECTED_PATHS = (
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".claude/hooks/",
)

FILE_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
SHELL_TOOLS = {"Bash", "PowerShell"}

# Operations that modify or delete a file when they appear in a shell command.
MUTATING = re.compile(
    r"""(?ix)
    (?<![\w-])(
        rm | rmdir | del | erase | unlink | shred | truncate | tee
      | mv | move | ren | rename | move-item | rename-item
      | remove-item | clear-content | set-content | add-content | out-file
      | new-item | set-item | copy-item | cp | copy | xcopy | robocopy
      | sed\s+-[a-z]*i | perl\s+-[a-z]*i | dd | install | ln
      | git\s+(?:rm|mv|restore|checkout|reset|clean|stash|apply|rebase|merge)
      | os\.(?:remove|unlink|rename|replace|truncate) | shutil\.\w+
      | \.write_text | \.write_bytes | \.unlink | \.rename | \.replace
      | open\([^)]*['"][^'"]*[wax+][^'"]*['"]
    )(?![\w-])
    | (?<![\d&])>{1,2}(?!&)          # output redirection
    """
)


def normalise(text: str) -> str:
    return text.replace("\\", "/").lower()


def protected_in_path(path: str) -> str | None:
    """Return what is protected if a file-tool target path is protected."""
    norm = normalise(path)
    base = norm.rsplit("/", 1)[-1]
    for name in PROTECTED_NAMES:
        if base == name.lower():
            return name
    for fragment in PROTECTED_PATHS:
        if fragment.endswith("/"):
            if f"/{fragment}" in f"/{norm}":
                return fragment
        elif norm == fragment or norm.endswith(f"/{fragment}"):
            return fragment
    return None


def protected_in_command(command: str) -> str | None:
    """Return what is protected if a shell command mentions a protected file."""
    norm = normalise(command)
    for name in PROTECTED_NAMES:
        if re.search(rf"(?<![\w.-]){re.escape(name.lower())}(?![\w-])", norm):
            return name
    for fragment in PROTECTED_PATHS:
        if fragment.rstrip("/") in norm:
            return fragment
    return None


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # Fail closed: if the input cannot be understood, do not allow the call.
        print("protect_files: could not parse hook input; blocking.", file=sys.stderr)
        return 2

    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}

    if tool in FILE_TOOLS:
        path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        hit = protected_in_path(path)
        if hit:
            print(f"Blocked: '{hit}' is protected and must never be edited.", file=sys.stderr)
            return 2

    if tool in SHELL_TOOLS:
        command = str(tool_input.get("command") or "")
        hit = protected_in_command(command)
        if hit and MUTATING.search(command):
            print(
                f"Blocked: this command may modify or delete protected '{hit}'. "
                "Protected files must never be edited or deleted.",
                file=sys.stderr,
            )
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
