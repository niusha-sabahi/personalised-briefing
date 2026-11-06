# Requirements

Tiers: **M** Must have (mandatory per task.md) · **S** Should have (quality, security, Python standards) · **C** Could have (nice to have, only after M and S).

Status: `[ ]` not started · `[~]` in progress or partly done · `[x]` complete and verified (tests pass, no regressions). Update the marker in the same change that affects it, and never mark `[x]` without evidence (a passing test or a manual check). When a requirement with sub-requirements (such as M3) is marked `[x]`, all its sub-requirements must be `[x]` too.

## M – Must have

**Briefing behaviour**
- [ ] M1. Generate one briefing per persona: Healthcare Policy Analyst (USA) and Tech Startup Founder (London). A persona is data: an id, a position, a location, and a list of topic ids (see M3.1). A persona's briefing is built from sources tagged with those topics.
- [ ] M2. Use only sources from `sources_06-05-25.json`. Do not fetch anything else.
- [ ] M3. Sources are embedded and organised by topic tag, not by persona. Embeddings and tags never reference a persona, so a new persona only needs a new list of topic ids.
  - [ ] M3.1. Topic taxonomy: a committed data file (for example `topics.yaml`) where each topic has a stable `id`, a `label`, and a short `description` used for embedding. It must include at least these topics, taken from the persona interests in task.md: healthcare reform, public health data, telemedicine, pharmaceutical innovation, health equity, government policy updates, artificial intelligence, venture capital, startup funding, SaaS trends, product management. Extra topics are allowed and are not limited to these.
  - [ ] M3.2. Embed each source (once, using cleaned text) and each topic description with an OpenAI embedding model.
  - [ ] M3.3. Multi-label tagging: a source gets every topic whose cosine similarity is at or above a configured threshold, capped at a configured maximum number of tags per source. A source may have several tags or none. Each tag keeps its similarity score. Untagged sources are never used in a briefing.
  - [ ] M3.4. For a persona, candidate sources are those carrying at least one of the persona's topic ids and passing the recency filter (M4). Rank them by their best score among the persona's topics, with ties broken by URL, and select the top-k. Selection must include a per-topic minimum where available, so one topic cannot crowd out the others.
- [ ] M4. Recency filter: exclude any source with a publication date before 2025-04-06 (one month before 2025-05-06). Derive the date from the URL path or the text, and document the rule used. Sources with no determinable date are excluded.
- [ ] M5. Generate the briefing with the most suitable OpenAI embedding model, using only the selected sources as context.
- [ ] M6. Output is Markdown.
- [ ] M7. Every claim in the briefing links to a source, and a "Sources" section lists title and URL for each source used. Every cited URL must exist in the input file.
- [ ] M8. Content must be relevant to the persona, and a briefing contains no off-topic text.
  - Every source in a briefing carries at least one of the persona's topic ids, and the briefing is organised into sections by topic.
  - A source that is only partly about the persona's topics may still be used, but only its related parts appear in the briefing. Unrelated parts of the article (other subjects, ads, navigation, sidebars, promotional or boilerplate text) are left out.
  - The generation prompt states this rule explicitly: use only the passages relevant to the persona's topics, and omit everything else from each source.
  - Every statement in a topic section must be traceable to a cited source passage that relates to that section's topic.

**Application**
- [~] M9. Backend is a FastAPI server exposing at least: `GET /health`, `GET /topics` (the taxonomy), and an endpoint that returns a persona's briefing as Markdown (for example `GET /briefings/{persona_id}`, with `persona_id` being `healthcare-policy-analyst` or `tech-founder`).
- [ ] M10. A minimal frontend (any framework) that selects a persona and renders the Markdown briefing.
- [~] M11. The OpenAI key is read from the environment or `.env`. It is never committed or logged, and `.env` stays gitignored.

**Project and delivery**
- [x] M12. A uv project: `pyproject.toml` plus a committed `uv.lock`, a `.python-version` file, and a `.venv/` created by `uv sync`. All commands run through the venv (`uv run ...`).
- [~] M13. Plain Python only, with no notebooks.
- [~] M14. `README.md` covers prerequisites, setup (`uv sync`, copy `.env.example` to `.env`), how to run the server and frontend, how to call the API, and how to run the tests.
- [ ] M15. Extension: an Agent Skill (a `SKILL.md` with name and description frontmatter, following agentskills.io) that lets a coding agent set up, start and test the application, including calling the endpoints and checking that the output is valid.
- [~] M16. Deliver everything as one private GitHub repository. The repo root is the project root (the existing `takehome/` git repo, with its `origin` remote), and it contains all of the following, committed:
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
- [~] S1. `src/` layout with a named package, for example `src/briefing/`, split into modules: `config`, `sources` (load, clean, date), `topics` (taxonomy and personas), `embeddings`, `tagging` (multi-label assignment), `retrieval` (persona selection from tags), `generation`, `api`, `models`. `pyproject.toml` defines the package and a script entry point.
- [x] S2. Dependencies are split into runtime and dev groups (`uv add --dev`). Dev tools: `ruff` (lint and format), `mypy` or `pyright` (type checking), `pytest`, `pytest-asyncio` or `httpx` for API tests, and `pytest-cov`.
- [x] S3. Ruff and the type checker are configured in `pyproject.toml`. Both must pass with zero errors, and type hints are used throughout. Ruff enables the `D` (pydocstyle) rules with the Google convention, so a missing or malformed docstring on a public module, function, class or method fails lint.
- [~] S4. Pre-commit hooks (ruff, type check) and CI (a GitHub Actions workflow running `uv sync --locked`, lint, type check and tests).
- [x] S5. A `.env.example` with placeholder values, and `.gitignore` entries for `.venv/`, `.env`, caches and coverage output.

**Configuration and security**
- [x] S6. Settings are loaded with `pydantic-settings`: API key, model names, tagging threshold, max tags per source, top-k, per-topic minimum, cutoff date, and cache path. No hard-coded secrets or model names in code.
- [~] S7. The key is wrapped as `SecretStr`. Logs and error responses never contain it. Check git history for a leaked key before pushing.
- [ ] S8. Source text is untrusted. The prompt separates instructions from source content and tells the model to ignore instructions found inside sources. Generated Markdown is sanitised or escaped when rendered in the frontend.
- [ ] S9. Pydantic models validate request and response shapes, and validate the topic and persona data files at startup (unique topic ids, every persona topic id exists in the taxonomy). Path parameters are restricted to known personas, and unknown ones return 404.

**Correctness and robustness**
- [ ] S10. Clean scraped text before embedding: strip nav links, `[iframe](javascript:false)` and boilerplate, collapse whitespace, and truncate or chunk to the embedding token limit. Skip entries with empty or tiny text.
- [ ] S11. Cache embeddings on disk (sources keyed by URL and content hash, topics keyed by id and description hash) so repeat runs make no API calls. Tags are recomputed from cached embeddings, so changing the threshold or adding a topic only embeds the new topic. Cache briefings in memory per persona.
- [ ] S12. Deterministic behaviour where possible: fixed top-k, threshold and tag cap, stable sort (ties broken by URL), `temperature` set to the lowest value the model supports, and embeddings batched in a fixed order.
- [ ] S13. Handle OpenAI errors: timeouts, rate limits (retry with backoff), and auth failures. Return 502 or 503 with a clear message, never a stack trace. Handle the case where no sources pass the filters by returning a clear "no relevant recent sources" response.
- [ ] S14. Post-generation check that every `[n]` citation or URL in the briefing maps to a selected source. Drop or flag any that do not.
- [ ] S15. Logging with the standard `logging` module, with levels set by config.

**Testing**
- [ ] S16. Unit tests with the OpenAI client mocked, covering: date extraction (URL form, text form, missing, malformed), the cutoff boundary (2025-04-05 excluded, 2025-04-06 included), text cleaning, multi-label tagging (several tags, no tags, threshold boundary, tag cap), persona selection from tags (union across topics, per-topic minimum, top-k, tie-break), citation validation, and taxonomy and persona validation (duplicate topic id, unknown topic id in a persona).
- [ ] S17. API tests with FastAPI `TestClient` covering: `/health`, a valid persona, an unknown persona (404), OpenAI failure (502 or 503), and the empty-results case.
- [ ] S18. Data-integrity tests over the real JSON: no selected source predates the cutoff, and every required topic in M3.1 exists in the taxonomy. With the live API (opt-in), each required topic has at least one tagged source.
- [ ] S19. One opt-in integration test (marked, skipped without a key) that runs the whole pipeline against the live API and checks that the output is non-empty Markdown with valid references.

**Documentation**
- [~] S20. The README has a short architecture overview (one paragraph or a small diagram of the flow: clean, embed, tag, retrieve, generate, validate citations) that matches the code. Endpoints have a `summary`, response models and error responses so `/docs` serves as the API reference. Config options are documented once, in `.env.example` and the settings class.

## C – Could have

- [ ] C1. Dockerfile using the uv image, plus `docker compose` for one-command startup.
- [ ] C2. Add an LLM-based relevance rerank or per-section summaries (policy, pharma, telemedicine) after embedding retrieval.
- [ ] C3. Load personas from a YAML or JSON file so new personas need no code changes, and add a `POST /briefings` endpoint that accepts a custom persona (position, location, topic ids).
- [ ] C4. Streaming generation (SSE) for the frontend.
- [ ] C5. A coverage threshold enforced in CI, and a `Makefile` or `uv run` task aliases (`lint`, `test`, `serve`).
- [ ] C6. Structured JSON logging and request IDs.
