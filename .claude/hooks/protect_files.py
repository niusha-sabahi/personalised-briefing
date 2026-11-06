"""PreToolUse hook: protect the project's key files and keep secret values unread.

Reads the tool call as JSON on stdin. Exit code 2 blocks the call and shows
stderr to the agent. Any other exit code lets the call through.

Protected from edits and deletion:
  - by filename:  .env, sources_06-05-25.json, task.md
  - by path:      .claude/settings.json, .claude/settings.local.json,
                  everything under .claude/hooks/ (this hook included)

Protected from being read (secret values):
  - .env and any .env.* file other than the placeholder files below, via the
    Read and Grep tools and via shell commands that read file contents.
  - Printing secret environment variables (printenv, echo $SOME_KEY, ...).
  - Listing variable NAMES is allowed:  grep -oE '^[A-Za-z_]+' .env

File tools (Edit/Write/NotebookEdit) are blocked outright for protected files.
Shell tools (Bash/PowerShell) are blocked when the command names a protected
file together with a modifying or deleting operation. Reading task.md or the
sources JSON is allowed. Shell matching is best-effort.

Deliberate exceptions that keep harmless commands from being blocked:
  - .env.example / .env.sample / .env.template are placeholder files, not .env.
  - The text of a `git commit -m "..."` message is not analysed (it is only
    prose), unless it contains command substitution that could run code.
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
READ_TOOLS = {"Read", "Grep"}

# Words that modify or delete a file when they appear in a shell command.
MUTATING_WORDS = re.compile(
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
    """
)

# Output redirection (> or >>), but not 2>&1 style descriptor duplication.
REDIRECT = re.compile(r"(?<![\d&])>{1,2}(?!&)")

# Placeholder files that merely look like .env.
PLACEHOLDER_ENV = re.compile(r"\.env\.(?:example|sample|template)(?![\w-])")

# The -m / --message argument of `git commit`, double or single quoted.
COMMIT_MESSAGE = re.compile(r"""(-m|--message)(?:\s+|=)("(?:[^"\\]|\\.)*"|'[^']*')""")

# Commands that can show file contents (or run code that could).
CONTENT_READERS = re.compile(
    r"""(?ix)
    (?<![\w-])(
        cat | bat | type | more | less | head | tail | nl | tac | strings | xxd | od
      | get-content | gc | select-string | sls | sed | awk | grep | egrep | fgrep | rg
      | findstr | source | python\d* | node | import-csv | foreach-object | copy | cp
    )(?![\w-])
    """
)

# The one allowed way to look at .env: print variable names only, or just test.
#   grep -oE '^[A-Za-z_]+' .env      (names)      grep -c/-q/-l pattern .env  (no values)
NAMES_ONLY = re.compile(
    r"""(?ix)^\s*grep\s+(?:
        -[a-z]*o[a-z]*\s+(?:-e\s+)?['"]\^\[A-Za-z_\]\+['"]\s+[^\s;&|<>`$()]*\.env
      | -[a-z]*[cql][a-z]*\s+[^;&|<>`$()]*
    )\s*$"""
)

# Printing secret environment variables.
SECRET_VAR = r"(?:env:)?\w*(?:key|token|secret|passw)\w*"
ENV_PRINTERS = re.compile(
    rf"""(?ix)
    (?<![\w-])printenv(?![\w-])
  | ^\s*(?:env|set)\s*$
  | (?<![\w-])(?:get-childitem|gci|ls|dir|get-item)\s+env:
  | (?<![\w-])(?:echo|write-host|write-output|print|printf)\b[^|;&\n]*[$%]\{{?{SECRET_VAR}
    """
)

# A shell command names .env itself (not .env.example and friends).
NAMES_ENV = re.compile(r"(?<![\w.-])\.env(?![\w-])")


def normalise(text: str) -> str:
    """Lower-case a path or command and use forward slashes."""
    return text.replace("\\", "/").lower()


def strip_commit_messages(command: str) -> str:
    """Remove plain-text `git commit -m` messages so prose is not mistaken for commands.

    A message containing a backtick or a `$(...)` substitution (other than the
    usual `$(cat <<'EOF' ...)` heredoc) is kept, since it could run code.
    """
    if not re.search(r"\bgit\s+commit\b", command, re.IGNORECASE):
        return command

    def blank(match: re.Match[str]) -> str:
        body = match.group(2)
        if "`" in body or re.search(r"\$\((?!\s*cat\s*<<)", body):
            return match.group(0)
        return f"{match.group(1)} ''"

    return COMMIT_MESSAGE.sub(blank, command)


def is_mutating(command: str) -> bool:
    """Return True if the command contains a modifying word or a redirect."""
    return bool(MUTATING_WORDS.search(command) or REDIRECT.search(command))


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


def is_secret_env_path(path: str) -> bool:
    """Return True if a path is .env or a .env.* file other than a placeholder."""
    base = normalise(path).rsplit("/", 1)[-1]
    is_env = base == ".env" or base.startswith(".env.")
    return is_env and not PLACEHOLDER_ENV.fullmatch(base)


def protected_in_command(command: str) -> str | None:
    """Return what is protected if a shell command mentions a protected file."""
    norm = PLACEHOLDER_ENV.sub("", normalise(command))
    for name in PROTECTED_NAMES:
        if re.search(rf"(?<![\w.-]){re.escape(name.lower())}(?![\w-])", norm):
            return name
    for fragment in PROTECTED_PATHS:
        if fragment.rstrip("/") in norm:
            return fragment
    return None


def secret_read_in_command(command: str) -> str | None:
    """Return a reason if a shell command would read or print secret values."""
    if ENV_PRINTERS.search(command):
        return "printing secret environment variables"
    norm = PLACEHOLDER_ENV.sub("", normalise(command))
    if NAMES_ENV.search(norm) and CONTENT_READERS.search(command) and not NAMES_ONLY.match(command):
        return "reading the contents of .env"
    return None


def block(message: str) -> int:
    """Print a block message for the agent and return the blocking exit code."""
    print(message, file=sys.stderr)
    return 2


def main() -> int:
    """Check one tool call read from stdin; return 2 to block it, 0 to allow it."""
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # Fail closed: if the input cannot be understood, do not allow the call.
        return block("protect_files: could not parse hook input; blocking.")

    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}

    if tool in FILE_TOOLS:
        path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        hit = protected_in_path(path)
        if hit:
            return block(f"Blocked: '{hit}' is protected and must never be edited.")

    if tool in READ_TOOLS:
        path = str(tool_input.get("file_path") or tool_input.get("path") or "")
        if is_secret_env_path(path):
            return block(
                "Blocked: do not read secret values. To list variable names only, "
                "run: grep -oE '^[A-Za-z_]+' .env"
            )

    if tool in SHELL_TOOLS:
        command = strip_commit_messages(str(tool_input.get("command") or ""))
        reason = secret_read_in_command(command)
        if reason:
            return block(
                f"Blocked: {reason}. Never read secret values. To list variable names "
                "only, run: grep -oE '^[A-Za-z_]+' .env"
            )
        hit = protected_in_command(command)
        if hit and is_mutating(command):
            return block(
                f"Blocked: this command may modify or delete protected '{hit}'. "
                "Protected files must never be edited or deleted."
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
