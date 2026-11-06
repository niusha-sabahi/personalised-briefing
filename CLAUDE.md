# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

The project scaffold is in place: a uv project with a `src/briefing/` package (module placeholders plus `config` and a `/health` API), ruff, mypy (strict) and pytest configured, pre-commit and CI config written. The briefing pipeline is not implemented yet. See [README.md](README.md) and REQUIREMENTS.md for progress.

Commands (all through uv; if `uv` is not on PATH, use `python -m uv`):
- `uv sync`: install into `.venv`.
- `uv run ruff format` and `uv run ruff check --fix`: format and lint (the `D` docstring rules are on).
- `uv run mypy src`: type check.
- `uv run pytest --cov`: full test suite.
- `uv run briefing`: serve the API on http://127.0.0.1:8000.

Gotcha: the protect hook matches shell commands loosely (best-effort). `.env.example` and the text of `git commit -m` messages are exempt, but a command that names `.env` itself and contains `>` or a mutating word is still blocked even when harmless. The hook also blocks reading `.env` or `.env.*` (other than the placeholders) and printing secret environment variables. Create such files with the Write tool, and avoid redirects in commands that name `.env`.

## Requirement tracking and regression rule

Every requirement in [REQUIREMENTS.md](REQUIREMENTS.md) carries a status marker (`[ ]` not started, `[~]` in progress, `[x]` complete and verified). In every development session:

1. **Keep statuses current.** Update the markers in REQUIREMENTS.md in the same change that affects them. Mark `[x]` only with evidence (a passing test or a manual check), never on the strength of code merely being written.
2. **Check for regressions before finishing.** Once the test suite exists, run it (plus lint and type check, as set up) before ending the session and confirm that every requirement previously marked `[x]` still holds. If something broke, fix it, or downgrade its marker to `[~]` and say so. Before the test suite exists, re-check the previously completed requirements by hand.
3. **End the session with a summary** for the user, covering: requirements completed this session (IDs), requirements started but unfinished, any requirement that regressed or was downgraded, the test, lint and type-check results, and the overall tally (done / total per tier M, S, C).

## Documentation rule

At the end of every prompt you complete (not only at the end of a session), before reporting back:

1. **Update [README.md](README.md).** Add anything the change makes true or necessary: the "Work completed" entry, new or changed setup, run, API or test instructions, new config or environment variables, and the requirement tally. Replace placeholders such as "instructions will be added" once the thing exists. Remove or correct statements that are no longer true. Do not add a README entry for trivial changes.
2. **Keep the code documented to industry standard, and no more than that.**
   - Every module has a one-line docstring saying what it is for. Every public function, class and method has a docstring in Google style: a summary line, plus `Args`, `Returns` and `Raises` only where they add information beyond the type hints. Private helpers get one only if their purpose is not obvious from the name.
   - Comments explain **why** (a non-obvious decision, a constraint, a workaround, the reason for a threshold), never what the code already says. Do not narrate code, restate signatures, or leave commented-out code or stale TODOs.
   - Type hints are the primary documentation of types. Do not repeat types in docstrings.
   - Give FastAPI endpoints a `summary`, response models and error responses, so the generated OpenAPI docs at `/docs` are the API reference. Do not duplicate that reference in prose.
   - Config options are documented once, in `.env.example` and the settings class. The README links to them rather than repeating them.
3. **README architecture overview.** Keep a short architecture section in the README (one paragraph or a small diagram of the flow: clean, embed, tag, retrieve, generate, validate citations). Update it whenever the pipeline changes, so it always matches the code. Keep it to the big picture; module detail belongs in docstrings.
4. **Write the README setup and run steps as soon as the app first runs** (and keep them working afterwards), not at the end. A fresh clone must be able to follow them (REQUIREMENTS.md M14 and M16).
5. **Docstring lint.** Once ruff is configured, it must enable the `D` (pydocstyle) rules with the Google convention (REQUIREMENTS.md S3). Fix lint failures by writing proper docstrings, not by disabling the rules.
6. **Update CLAUDE.md** when commands, architecture or conventions change (see the Status section).
7. Do not create extra documentation files (separate design docs, changelogs, per-module READMEs) unless the user asks. The README, REQUIREMENTS.md, CLAUDE.md, docstrings and the Agent Skill are the documentation set.

## Testing and quality gate

At the end of every prompt you complete (when your loop is finished, before reporting back), once the tooling exists:

1. **Update the tests for the change.** Add tests for new behaviour. Modify tests whose expected behaviour legitimately changed. Delete tests for removed behaviour. Never weaken, skip or delete a test just to make the suite pass; if a test fails, fix the code or explain why the test's expectation was wrong. Follow the test plan in REQUIREMENTS.md (S16 to S19), and mock the OpenAI client in unit tests.
2. **Format and lint:** run `uv run ruff format` and `uv run ruff check --fix`, then the type checker. All must finish with zero errors.
3. **Run the entire test suite** (`uv run pytest`), not only the tests you touched. All must pass.
4. **Report the results** in your closing message: tests added, changed or removed, and the format, lint, type-check and test results. If anything could not be run or failed, say so plainly. Until the tooling exists, say that instead.

A `Stop` hook ([.claude/hooks/quality_gate.py](.claude/hooks/quality_gate.py), configured in `.claude/settings.json`) enforces steps 2 and 3 automatically: it runs format, lint, mypy and the tests (skipping `integration`-marked ones) and blocks you from finishing until they pass. It does nothing until `pyproject.toml` and a test exist, and gives up with a warning after 3 consecutive failures in a session. Steps 1 and 4 still apply, because only you can judge which tests a change needs.

## The assignment (summary of task.md)

Build a personalised briefing generator:

- **Backend:** FastAPI server. Frontend can be any framework (not judged).
- **Personas:** (1) Healthcare Policy Analyst, USA — healthcare reform, public health data, telemedicine, pharma innovation, health equity, government policy. (2) Tech Startup Founder, London — AI, venture capital, startup funding, SaaS trends, product management.
- **Models:** OpenAI models: "GPT-5.6 luna" for generation plus any OpenAI embedding model. Put model names in config, not code.
- **Tooling:** uv project (`pyproject.toml`, `uv.lock`, `.venv`); run everything via `uv run`. The full prioritised checklist (M/S/C tiers) is in [REQUIREMENTS.md](REQUIREMENTS.md).
- **Output:** Markdown briefing, relevant to the person's interests, with references to sources.
- **Recency rule:** only use sources published no more than 1 month before the newest source date (6 May 2025, so on or after ~6 Apr 2025). Sources have no date field; the date has to be derived from the URL path or the text.
- **Extension:** after the briefing app works, write an [Agent Skill](https://agentskills.io/home) that lets a coding agent test the application.
- **Deliverables:** README with run instructions, plain Python (no notebooks), private GitHub repo.

## Data

[sources_06-05-25.json](sources_06-05-25.json) (~7.7 MB) has the shape `{"reference_by_id": {<uuid>: {source_type, url, title, description, text}}}` with 273 entries, all `source_type: "web_results"`. `text` is scraped page content with lots of navigation and link boilerplate (markdown links, `[iframe](javascript:false)`), so clean it before embedding or prompting. Sources cover many topics, so relevance filtering per persona (embeddings) is the core step.

## Secrets

`.env` holds `OPENAI_API_KEY` and is gitignored. The `.gitignore` also covers `.venv/`, `__pycache__/` and `.idea/`.

Never read the values of secrets. This applies to `.env` and to any other file, variable or output that may hold a key, token or password:
- Do not open `.env` with the Read tool, or `cat`, `head`, `type`, `Get-Content` or similar, and do not print environment variables that hold secrets (no `printenv`, `env`, `echo $OPENAI_API_KEY`, `Get-ChildItem Env:`).
- If you need to know which variables exist, read the names from `.env.example` and the `Settings` class, which list every one. Do not inspect `.env` at all: the `Read(.env)` deny rule and the protect hook block the Read and Grep tools and shell commands that read it, and that includes a names-only `grep`. To confirm that a key is actually set, ask the user or run the app, and do not try another route to the file.
- Never put a secret value in code, tests, logs, error messages, commit messages, README examples, or your replies. Use placeholders such as `your-key-here` (see `.env.example`).
- The application reads the key itself through `Settings` (`SecretStr`). Tests use fake values like `sk-test-secret`. Live-API checks run through the app or the opt-in integration test, never by you handling the key.
- If a secret value is ever exposed (for example in tool output), tell the user straight away so they can rotate it, and do not repeat it.

## Protected files

`.env`, `sources_06-05-25.json` and `task.md` must never be edited or deleted. This is enforced by deny rules plus a `PreToolUse` hook ([.claude/settings.json](.claude/settings.json), [.claude/hooks/protect_files.py](.claude/hooks/protect_files.py)). The settings file, `.claude/settings.local.json` and everything under `.claude/hooks/` are protected the same way. Do not try to work around the block.

The hook scripts have regression tests ([tests/test_protect_hook.py](tests/test_protect_hook.py), [tests/test_quality_gate.py](tests/test_quality_gate.py)), which run with the normal suite.

To unprotect the settings and hook files (done by the user, by hand):
1. In `.claude/settings.json`, delete the deny rules for `/.claude/settings.json`, `/.claude/settings.local.json` and `/.claude/hooks/**` (the three `Edit(...)` and three `Write(...)` lines). Then make sure the last remaining entry in the `deny` array has no trailing comma, or the JSON is invalid.
2. In `.claude/hooks/protect_files.py`, replace the `PROTECTED_PATHS` tuple with `PROTECTED_PATHS = ()`. Keep the name defined.
3. Restart the session so the changes load.

## Environment notes

- Windows with PowerShell; the Bash tool is also available.
