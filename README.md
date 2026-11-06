# Personalised Briefing

A FastAPI service that generates Markdown briefings, with cited sources, for different personas from a set of web sources. See [task.md](task.md) for the assignment and [REQUIREMENTS.md](REQUIREMENTS.md) for the full requirements.

## Setup

Prerequisites: [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for you if needed) and an OpenAI API key.

```
uv sync                      # creates .venv and installs everything
cp .env.example .env         # then fill in OPENAI_API_KEY (options are documented in .env.example)
```

## Run

```
uv run briefing              # serves the API on http://127.0.0.1:8000
curl http://127.0.0.1:8000/health
```

Interactive API docs are at `http://127.0.0.1:8000/docs`. Only `/health` exists so far; the briefing endpoints and frontend are still to be built.

## Develop

```
uv run ruff format && uv run ruff check --fix   # format and lint (includes docstring rules)
uv run mypy src                                 # type check
uv run pytest --cov                             # tests
uv run pre-commit install                       # optional: run format/lint/type check on each commit
```

## Architecture (planned)

Sources are never matched to a persona directly. Each source is cleaned, embedded once and tagged with topics from a shared taxonomy. A persona is just a list of topic ids.

```
sources JSON -> clean + extract date -> recency filter (>= 2025-04-06)
             -> embed (cached) -> multi-label topic tags
persona topics -> select top-k tagged sources (per-topic minimum)
               -> generate Markdown briefing (relevant passages only)
               -> validate citations against selected sources -> API / frontend
```

## Work completed

Status: planning and the project scaffold are done. **The briefing pipeline itself is not implemented yet** (only `/health` works).

- **Assignment analysis:** reviewed `task.md` and inspected `sources_06-05-25.json` (273 web sources, fields `url`, `title`, `description`, `text`, and no date field).
- **Requirements:** wrote [REQUIREMENTS.md](REQUIREMENTS.md), a tiered list (Must / Should / Could) that is deterministic and testable. Key design decisions:
  - Sources are embedded and tagged by **topic** (multi-label), not by persona, so new personas only need a new topic list.
  - All 11 interests from the task are in the topic taxonomy, and extra topics are allowed.
  - Briefings contain only the passages relevant to the persona, cited to a source.
  - Recency cutoff of 2025-04-06, one month before the newest source.
  - uv project with a `.venv`, delivered as a single private GitHub repository, with an agent-neutral skill in `skills/`.
- **Repository guidance:** wrote [CLAUDE.md](CLAUDE.md) for coding agents, covering the assignment, the data format, secrets handling and protected files.
- **File protection:** `.env`, `sources_06-05-25.json` and `task.md` can never be edited or deleted, and the protection files are covered too. It uses deny rules in [.claude/settings.json](.claude/settings.json) and a `PreToolUse` hook in [.claude/hooks/protect_files.py](.claude/hooks/protect_files.py). Both layers were verified: the hook script against 44 simulated tool calls (all passed, including fail-closed on bad input), and in a live session (file edits rejected by the deny rules, mutating shell commands blocked by the hook, read-only access still allowed). Shell matching is best-effort.
- **Requirement tracking:** every requirement in [REQUIREMENTS.md](REQUIREMENTS.md) now has a status marker (`[ ]` not started, `[~]` in progress, `[x]` complete and verified). Current tally: 5 of 46 complete (M: 1/20, S: 4/20, C: 0/6; M includes the sub-requirements M3.1 to M3.4).
- **Session rule:** [CLAUDE.md](CLAUDE.md) now requires each development session to keep the statuses current, check for regressions (tests, lint and type check once they exist) before finishing, and end with a summary of the requirements completed, unfinished, or regressed.
- **Project scaffold:** uv project (Python 3.12, `uv.lock`) with a `src/briefing/` package split into the modules planned in S1, a `briefing` script entry point, a working `/health` endpoint, and `Settings` (pydantic-settings, `SecretStr` key, model names and tuning in config). Ruff (with docstring rules), mypy strict and pytest with coverage are configured and pass; pre-commit and a GitHub Actions workflow are written but not yet exercised. Ruff skips `.claude/`, which is tooling and protected.
- **Quality-gate hook:** a `Stop` hook ([.claude/hooks/quality_gate.py](.claude/hooks/quality_gate.py)) runs ruff format, ruff check, mypy and the tests at the end of every agent turn and blocks finishing until they pass (no-op until tests exist, gives up after 3 failed attempts). The file-protection hook was also fixed so `.env.example` and `git commit -m` message text no longer cause false blocks, while `.env` stays fully protected. Both hooks have tests in `tests/` (38 tests in the suite now).
- **Secret-reading protection:** CLAUDE.md now forbids reading secret values, and this is enforced two ways: a `Read(.env)` deny rule in `.claude/settings.json`, and the protect hook, which now also covers the Read and Grep tools, shell commands that read `.env` or `.env.*`, and printing secret environment variables (`.env.example` stays readable). Verified live with a decoy file: Read, `cat`, `echo $VAR` and `Get-ChildItem Env:` were all blocked. The hook tests cover these cases too.
- **Documentation rule:** [CLAUDE.md](CLAUDE.md) now requires, after every prompt, a README update and code documented through Google-style docstrings and why-comments only. Ruff's `D` rules will enforce docstrings (S3), and a new requirement S20 covers the README architecture overview and the OpenAPI docs.
