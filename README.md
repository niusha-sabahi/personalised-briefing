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

### Topics and personas

Topics (`topics.yaml`) and personas (`personas.yaml`) are plain data. A persona is an id, a position, a location and a list of topic ids; to add one, add an entry (no code changes). Both files are validated when loaded (unique slug ids, no unknown fields, every persona topic must exist). To check them:

```
uv run briefing topics                # valid? which topics does each persona follow?
```

### Publication dates and the recency filter

The sources have no date field, so each date is derived (strongest rule first): a full date in the URL, a year-month in the URL (refined from the text when it has a date in that month), a "Published/Posted/Released" label, an "Updated/Last update" label, then the first date near the top of the text. Dates after 2025-05-06 are ignored, and sources with no determinable date are excluded. A source is kept if published on or after 2025-04-06 (`CUTOFF_DATE`). To audit the result for every source (no API key needed):

```
uv run briefing dates                 # every source: KEEP/DROP, date, rule, URL
uv run briefing dates --only kept     # or --only excluded
```

## Develop

```
uv run ruff format && uv run ruff check --fix   # format and lint (includes docstring rules)
uv run mypy src                                 # type check
uv run pytest --cov                             # tests
uv run pre-commit install                       # once per clone: run format, lint, type check and tests on each commit
uv run pre-commit run --all-files               # run them on demand (needs Git 2.31 or newer)
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
- **Requirement tracking:** every requirement in [REQUIREMENTS.md](REQUIREMENTS.md) now has a status marker (`[ ]` not started, `[~]` in progress, `[x]` complete and verified). Current tally: 7 of 46 complete (M: 3/20, S: 4/20, C: 0/6; M includes the sub-requirements M3.1 to M3.4).
- **Session rule:** [CLAUDE.md](CLAUDE.md) now requires each development session to keep the statuses current, check for regressions (tests, lint and type check once they exist) before finishing, and end with a summary of the requirements completed, unfinished, or regressed.
- **Project scaffold:** uv project (Python 3.12, `uv.lock`) with a `src/briefing/` package split into the modules planned in S1, a `briefing` script entry point, a working `/health` endpoint, and `Settings` (pydantic-settings, `SecretStr` key, model names and tuning in config). Ruff (with docstring rules), mypy strict and pytest with coverage are configured and pass; pre-commit and a GitHub Actions workflow are written but not yet exercised. Ruff skips `.claude/`, which is tooling and protected.
- **Quality-gate hook:** a `Stop` hook ([.claude/hooks/quality_gate.py](.claude/hooks/quality_gate.py)) runs ruff format, ruff check, mypy and the tests at the end of every agent turn and blocks finishing until they pass (no-op until tests exist, gives up after 3 failed attempts). The file-protection hook was also fixed so `.env.example` and `git commit -m` message text no longer cause false blocks, while `.env` stays fully protected. Both hooks have tests in `tests/`.
- **Secret-reading protection:** CLAUDE.md now forbids reading secret values, and this is enforced two ways: a `Read(.env)` deny rule in `.claude/settings.json`, and the protect hook, which now also covers the Read and Grep tools, shell commands that read `.env` or `.env.*`, and printing secret environment variables (`.env.example` stays readable). Verified live with a decoy file: Read, `cat`, `echo $VAR` and `Get-ChildItem Env:` were all blocked. The hook tests cover these cases too.
- **Documentation rule:** [CLAUDE.md](CLAUDE.md) now requires, after every prompt, a README update and code documented through Google-style docstrings and why-comments only. Ruff's `D` rules will enforce docstrings (S3), and a new requirement S20 covers the README architecture overview and the OpenAPI docs.
- **Development plan:** [CLAUDE.md](CLAUDE.md) now holds the architecture, a data-driven summary of what the sources look like, and an 11-stage plan (data foundation first, then taxonomy, embeddings and tagging, retrieval, generation, API, frontend, hardening, Agent Skill, delivery) with a status column. Confirmed: the generation model is `gpt-5.6-luna` and it takes no temperature setting.
- **Stage 1, data foundation (done):** `sources.py` loads the JSON (dropping 5 duplicate URLs, 268 remain), cleans scraped text (links to anchor text, navigation, consent banners, images and repeated menu lines removed; about 64% of the text is kept), derives publication dates with the ordered rules above, and applies the recency filter: 104 of 268 sources pass. `uv run briefing dates` audits every decision. The cutoff boundary (2025-04-05 excluded, 2025-04-06 included), every date rule, cleaning and the real data file are covered by tests (124 in the suite). Writing the tests exposed a flaw in the first cleaning rule, which deleted genuine sentences that mentioned "cookies", so the boilerplate rule now has two tiers.
- **Stage 2, taxonomy and personas (done):** `topics.yaml` (the 11 topics from the task, each with a description written to be embedded) and `personas.yaml` (the two personas), loaded and validated by `briefing.topics`, plus `uv run briefing topics`. Descriptions never mention a persona, which a test enforces; that test caught a "founders" in one description. `government-policy-updates` is scoped to health policy on purpose, so unrelated EU and education policy pages are not tagged with it. 153 tests in the suite now.
- **Tests on every commit:** the pre-commit config now also runs the test suite (without the opt-in live-API test), so a commit is checked by ruff format, ruff check, mypy and pytest. Verified on explicit files; `pre-commit run --all-files` needs Git 2.31 or newer.


## Future Work
- Check each article for data validity since the agentic coding model is non-deterministic
