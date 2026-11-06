# Requirements

Tiers: **M** Must have (mandatory per task.md) · **S** Should have (quality, security, Python standards) · **C** Could have (nice to have, only after M and S).

## M – Must have

**Briefing behaviour**
- M1. Generate one briefing per persona: Healthcare Policy Analyst (USA) and Tech Startup Founder (London), using the interests listed in task.md.
- M2. Use only sources from `sources_06-05-25.json`. Do not fetch anything else.
- M3. Embed each source and each persona's interests with an OpenAI embedding model, then rank sources by similarity to pick the relevant ones.
- M4. Recency filter: exclude any source with a publication date before 2025-04-06 (one month before 2025-05-06). Derive the date from the URL path or the text, and document the rule used. Sources with no determinable date are excluded.
- M5. Generate the briefing with the most suitable OpenAI embedding model, using only the selected sources as context.
- M6. Output is Markdown.
- M7. Every claim in the briefing links to a source, and a "Sources" section lists title and URL for each source used. Every cited URL must exist in the input file.
- M8. Content must be relevant to the persona. Each persona's briefing contains no off-topic items.

**Application**
- M9. Backend is a FastAPI server exposing at least: `GET /health` and an endpoint that returns a persona's briefing as Markdown (for example `GET /briefings/{persona_id}`, with `persona_id` being `healthcare-policy-analyst` or `tech-founder`).
- M10. A minimal frontend (any framework) that selects a persona and renders the Markdown briefing.
- M11. The OpenAI key is read from the environment or `.env`. It is never committed or logged, and `.env` stays gitignored.

**Project and delivery**
- M12. A uv project: `pyproject.toml` plus a committed `uv.lock`, a `.python-version` file, and a `.venv/` created by `uv sync`. All commands run through the venv (`uv run ...`).
- M13. Plain Python only, with no notebooks.
- M14. `README.md` covers prerequisites, setup (`uv sync`, copy `.env.example` to `.env`), how to run the server and frontend, how to call the API, and how to run the tests.
- M15. Extension: an Agent Skill (a `SKILL.md` with name and description frontmatter, following agentskills.io) that lets a coding agent set up, start and test the application, including calling the endpoints and checking that the output is valid.
- M16. Deliver everything as one private GitHub repository. The repo root is the project root (the existing `takehome/` git repo, with its `origin` remote), and it contains all of the following, committed:
  - Backend source in `src/`, the frontend, and `tests/`.
  - `pyproject.toml`, `uv.lock`, `.python-version`, `.gitignore`, `.env.example`, and `README.md`.
  - The input data file `sources_06-05-25.json`, so the app runs after a clone with no extra downloads.
  - The Agent Skill, inside the repo at `skills/<skill-name>/SKILL.md` (with any helper scripts in the same folder). It follows the open agentskills.io format and is agent-neutral: no Claude-specific paths, tool names or features, plain shell commands (`uv run ...`) that work on any OS, and only paths inside the repo. It must be usable by a coding agent driven by the provided OpenAI model.
  - Excluded from the repo: `.env`, `.venv/`, caches, and the macOS `__MACOSX/` folder.

  Done when all of these hold:
  - `gh repo view --json visibility` reports `PRIVATE`.
  - `git ls-files` shows every file listed above and no `.env` or `.venv/`.
  - The working tree is clean and `main` matches `origin/main`.
  - A fresh `git clone` into an empty directory followed by `uv sync` and the README's run steps starts the server and returns a briefing, using only a locally supplied `.env`.

## S – Should have

**Project layout and tooling**
- S1. `src/` layout with a named package, for example `src/briefing/`, split into modules: `config`, `sources` (load, clean, date), `embeddings`, `retrieval`, `generation`, `api`, `models`. `pyproject.toml` defines the package and a script entry point.
- S2. Dependencies are split into runtime and dev groups (`uv add --dev`). Dev tools: `ruff` (lint and format), `mypy` or `pyright` (type checking), `pytest`, `pytest-asyncio` or `httpx` for API tests, and `pytest-cov`.
- S3. Ruff and the type checker are configured in `pyproject.toml`. Both must pass with zero errors, and type hints are used throughout.
- S4. Pre-commit hooks (ruff, type check) and CI (a GitHub Actions workflow running `uv sync --locked`, lint, type check and tests).
- S5. A `.env.example` with placeholder values, and `.gitignore` entries for `.venv/`, `.env`, caches and coverage output.

**Configuration and security**
- S6. Settings are loaded with `pydantic-settings`: API key, model names, similarity threshold, top-k, cutoff date, and cache path. No hard-coded secrets or model names in code.
- S7. The key is wrapped as `SecretStr`. Logs and error responses never contain it. Check git history for a leaked key before pushing.
- S8. Source text is untrusted. The prompt separates instructions from source content and tells the model to ignore instructions found inside sources. Generated Markdown is sanitised or escaped when rendered in the frontend.
- S9. Pydantic models validate request and response shapes. Path parameters are restricted to known personas, and unknown ones return 404.

**Correctness and robustness**
- S10. Clean scraped text before embedding: strip nav links, `[iframe](javascript:false)` and boilerplate, collapse whitespace, and truncate or chunk to the embedding token limit. Skip entries with empty or tiny text.
- S11. Cache embeddings on disk (keyed by URL and a content hash) so repeat runs make no API calls. Cache briefings in memory per persona.
- S12. Deterministic behaviour where possible: fixed top-k and threshold, stable sort (ties broken by URL), `temperature` set to the lowest value the model supports, and embeddings batched in a fixed order.
- S13. Handle OpenAI errors: timeouts, rate limits (retry with backoff), and auth failures. Return 502 or 503 with a clear message, never a stack trace. Handle the case where no sources pass the filters by returning a clear "no relevant recent sources" response.
- S14. Post-generation check that every `[n]` citation or URL in the briefing maps to a selected source. Drop or flag any that do not.
- S15. Logging with the standard `logging` module, with levels set by config.

**Testing**
- S16. Unit tests with the OpenAI client mocked, covering: date extraction (URL form, text form, missing, malformed), the cutoff boundary (2025-04-05 excluded, 2025-04-06 included), text cleaning, ranking and top-k, citation validation, and persona config.
- S17. API tests with FastAPI `TestClient` covering: `/health`, a valid persona, an unknown persona (404), OpenAI failure (502 or 503), and the empty-results case.
- S18. A data-integrity test over the real JSON asserting that no selected source predates the cutoff.
- S19. One opt-in integration test (marked, skipped without a key) that runs the whole pipeline against the live API and checks that the output is non-empty Markdown with valid references.

## C – Could have

- C1. Dockerfile using the uv image, plus `docker compose` for one-command startup.
- C2. Add an LLM-based relevance rerank or per-section summaries (policy, pharma, telemedicine) after embedding retrieval.
- C3. Make personas data-driven (a YAML or JSON file) so new personas can be added without code changes, with a `POST /briefings` endpoint accepting a custom profile.
- C4. Streaming generation (SSE) for the frontend.
- C5. A coverage threshold enforced in CI, and a `Makefile` or `uv run` task aliases (`lint`, `test`, `serve`).
- C6. Structured JSON logging and request IDs.
