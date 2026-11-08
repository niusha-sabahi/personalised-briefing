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

Interactive API docs (the API reference) are at `http://127.0.0.1:8000/docs`. The server refuses to start if the settings or `topics.yaml` / `personas.yaml` are invalid. Endpoints:

```
curl http://127.0.0.1:8000/topics                                       # the topic taxonomy
curl http://127.0.0.1:8000/personas                                     # persona ids and their topics
curl http://127.0.0.1:8000/briefings/healthcare-policy-analyst          # Markdown briefing
curl "http://127.0.0.1:8000/briefings/tech-founder?format=json"         # JSON: markdown plus cited sources
```

The first briefing request embeds the sources (cached on disk) and calls the generation model, so it is slow and needs a working OpenAI key; later requests for the same persona are served from memory until the server restarts. Errors are JSON `{"detail": ...}`: 404 for an unknown persona or when no relevant recent sources exist, 503 when OpenAI is rate limiting or unreachable, 502 when OpenAI rejects the request or returns an unusable answer. They never include provider messages or stack traces. 

### Topics and personas

Topics (`topics.yaml`) and personas (`personas.yaml`) are plain data. A persona is an id, a position, a location and a list of topic ids; to add one, add an entry (no code changes). Both files are validated when loaded (unique slug ids, no unknown fields, every persona topic must exist). To check them:

```
uv run briefing topics                # valid? which topics does each persona follow?
```

### Embeddings and topic tags

Each recent source (title plus cleaned text, truncated to 16,000 characters) and each topic description is embedded with `EMBEDDING_MODEL`. Vectors are cached on disk in `CACHE_PATH`, keyed by a hash of the model and the text, so a repeat run makes no API calls and changing one topic description re-embeds only that topic. A source is tagged with every topic whose cosine similarity is at or above `TAGGING_THRESHOLD`, up to `MAX_TAGS_PER_SOURCE`. The default threshold is a placeholder until it is calibrated. This command calls the OpenAI API (it needs your key in the local env file) and prints the score distribution to choose it from:

```
uv run briefing tags                  # score quantiles, threshold sweep, top sources per topic
uv run briefing tags --threshold 0.40 # try another threshold without changing the settings
```

### Frontend

Open `http://127.0.0.1:8000/` for the web page: choose a persona and its briefing is shown, with a loading message (the first one is slow) and a retry button if something fails. It is one static page in `src/briefing/static/` with no build step. The briefing Markdown is rendered with [marked](https://github.com/markedjs/marked) and cleaned with [DOMPurify](https://github.com/cure53/DOMPurify) before it is inserted (only headings, paragraphs, lists, links and basic emphasis survive, and only `https://` links), and the page is served with a strict Content-Security-Policy that blocks inline script and any third-party request.

Both libraries are copied into `src/briefing/static/vendor/` (marked 18.1.1, DOMPurify 3.4.17), so the page loads nothing from a CDN and works offline. To upgrade one, download it into an empty directory with `npm pack marked@<version> dompurify@<version>`, copy `lib/marked.umd.js` and `dist/purify.min.js` (and the licence files) over the vendored copies, and update the pinned hashes in `tests/test_frontend.py`, which fail on any unplanned change.

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
uv run pytest --cov                             # tests (the sanitiser tests need Chrome, Chromium or Edge, else they skip)
uv run pre-commit install                       # once per clone: run format, lint, type check and tests on each commit
uv run pre-commit run --all-files               # run them on demand (needs Git 2.31 or newer)
```

## Architecture

Sources are never matched to a persona directly. Each source is cleaned, embedded once and tagged with topics from a shared taxonomy. A persona is just a list of topic ids. The first briefing request tags the sources; each persona's briefing is then built, validated and cached in memory.

```
sources JSON -> clean + extract date -> recency filter (>= 2025-04-06)
             -> embed (disk cache) -> multi-label topic tags
persona topics -> select top-k tagged sources (per-topic minimum)
               -> split into passages, keep those matching the persona's topics
               -> model returns structured JSON (bullets citing passage ids)
               -> validate citations, render Markdown from the source table
               -> API (FastAPI) -> frontend
```

## Working without an API key (temporary)

The API key we were given has expired and a replacement has been requested, so the live steps are paused. Delete this section once the key works and the checklist below is done.

**Workaround:** keep building everything that needs no key. Every OpenAI call sits behind a small interface (`Embedder`, and the generator in stage 5), and the tests use fakes, so stages 4 to 7 (retrieval, generation, API, frontend) are built and tested offline. A local stand-in embedder (for example TF-IDF) is deliberately not used: its scores are on a different scale from OpenAI's, so a threshold calibrated on it would be wrong.

**When a working key arrives** (put it in the local `.env` as `OPENAI_API_KEY`, with `GENERATION_MODEL` and `EMBEDDING_MODEL` as in `.env.example`):

1. Run `uv run briefing tags` and send the output back. Choose `TAGGING_THRESHOLD` from it (0.35 is a placeholder), then check that every persona topic has tagged sources and that the top sources per topic look relevant.
2. Calibrate the passage settings, `PASSAGE_THRESHOLD` and `MAX_PASSAGES_PER_SOURCE` (placeholders too), by reading the passages kept for a few real sources.
3. Decide on backfilling: count how often a selected source is dropped for having no relevant passage. If it is common, replace dropped sources with the next-best candidates so briefings keep `TOP_K` sources.
4. Check that `gpt-5.6-luna` accepts the structured-output request we send. `OpenAIGenerator` uses the Responses API (`responses.parse` with a Pydantic schema, `store=False`, no sampling parameters); if the model rejects it, switch to chat completions with the same schema.
5. Read a real briefing for each persona: relevant, cited, no off-topic text, and no hidden instructions from source text followed (S8). Check how many bullets and citations validation drops (`dropped_bullets`, `dropped_citations`); a high rate means the prompt or the passage topics need work, especially the rule that a bullet must cite a passage whose best topic is its section's topic.
6. Start the server (`uv run briefing`), open `http://127.0.0.1:8000/` and load each persona's briefing in a browser (also try `curl`; see Run), with the browser console open to check for Content-Security-Policy violations. Time the first request, which embeds every recent source, then generates: if it hits `OPENAI_TIMEOUT_SECONDS` (60 by default) or a client timeout, raise the setting or move the embedding to server startup. Check that a second request is instant, and that a bad key gives the clean 502 and not a stack trace.
7. Run the opt-in live integration test (S19) and the live data-integrity check (S18: each required topic has at least one tagged source).
8. Update the README, CLAUDE.md and REQUIREMENTS.md with the calibrated values, and mark the dependent requirements complete (M3.2, M3.3, M5, M8 and any others still partial).

## Work completed

Status: the whole pipeline and the API are built and tested offline with fake models (stages 0 to 7). **Nothing has run against the real OpenAI models yet**, because the API key expired; see the checklist above. Hardening, the Agent Skill and delivery remain.

- **Assignment analysis:** reviewed `task.md` and inspected `sources_06-05-25.json` (273 web sources, fields `url`, `title`, `description`, `text`, and no date field).
- **Requirements:** wrote [REQUIREMENTS.md](REQUIREMENTS.md), a tiered list (Must / Should / Could) that is deterministic and testable. Key design decisions:
  - Sources are embedded and tagged by **topic** (multi-label), not by persona, so new personas only need a new topic list.
  - All 11 interests from the task are in the topic taxonomy, and extra topics are allowed.
  - Briefings contain only the passages relevant to the persona, cited to a source.
  - Recency cutoff of 2025-04-06, one month before the newest source.
  - uv project with a `.venv`, delivered as a single private GitHub repository, with an agent-neutral skill in `skills/`.
- **Repository guidance:** wrote [CLAUDE.md](CLAUDE.md) for coding agents, covering the assignment, the data format, secrets handling and protected files.
- **File protection:** `.env`, `sources_06-05-25.json` and `task.md` can never be edited or deleted, and the protection files are covered too. It uses deny rules in [.claude/settings.json](.claude/settings.json) and a `PreToolUse` hook in [.claude/hooks/protect_files.py](.claude/hooks/protect_files.py). Both layers were verified: the hook script against 44 simulated tool calls (all passed, including fail-closed on bad input), and in a live session (file edits rejected by the deny rules, mutating shell commands blocked by the hook, read-only access still allowed). Shell matching is best-effort.
- **Requirement tracking:** every requirement in [REQUIREMENTS.md](REQUIREMENTS.md) now has a status marker (`[ ]` not started, `[~]` in progress, `[x]` complete and verified). Current tally: 20 of 46 complete (M: 8/20, S: 12/20, C: 0/6; M includes the sub-requirements M3.1 to M3.4).
- **Session rule:** [CLAUDE.md](CLAUDE.md) now requires each development session to keep the statuses current, check for regressions (tests, lint and type check once they exist) before finishing, and end with a summary of the requirements completed, unfinished, or regressed.
- **Project scaffold:** uv project (Python 3.12, `uv.lock`) with a `src/briefing/` package split into the modules planned in S1, a `briefing` script entry point, a working `/health` endpoint, and `Settings` (pydantic-settings, `SecretStr` key, model names and tuning in config). Ruff (with docstring rules), mypy strict and pytest with coverage are configured and pass; pre-commit and a GitHub Actions workflow are written but not yet exercised. Ruff skips `.claude/`, which is tooling and protected.
- **Quality-gate hook:** a `Stop` hook ([.claude/hooks/quality_gate.py](.claude/hooks/quality_gate.py)) runs ruff format, ruff check, mypy and the tests at the end of every agent turn and blocks finishing until they pass (no-op until tests exist, gives up after 3 failed attempts). The file-protection hook was also fixed so `.env.example` and `git commit -m` message text no longer cause false blocks, while `.env` stays fully protected. Both hooks have tests in `tests/`.
- **Tests on every commit:** the pre-commit config now also runs the test suite (without the opt-in live-API test), so a commit is checked by ruff format, ruff check, mypy and pytest. Verified on explicit files; `pre-commit run --all-files` needs Git 2.31 or newer.
- **Secret-reading protection:** CLAUDE.md now forbids reading secret values, and this is enforced two ways: a `Read(.env)` deny rule in `.claude/settings.json`, and the protect hook, which now also covers the Read and Grep tools, shell commands that read `.env` or `.env.*`, and printing secret environment variables (`.env.example` stays readable). Verified live with a decoy file: Read, `cat`, `echo $VAR` and `Get-ChildItem Env:` were all blocked. The hook tests cover these cases too.
- **Documentation rule:** [CLAUDE.md](CLAUDE.md) now requires, after every prompt, a README update and code documented through Google-style docstrings and why-comments only. Ruff's `D` rules will enforce docstrings (S3), and a new requirement S20 covers the README architecture overview and the OpenAPI docs.
- **Development plan:** [CLAUDE.md](CLAUDE.md) now holds the architecture, a data-driven summary of what the sources look like, and an 11-stage plan (data foundation first, then taxonomy, embeddings and tagging, retrieval, generation, API, frontend, hardening, Agent Skill, delivery) with a status column. Confirmed: the generation model is `gpt-5.6-luna` and it takes no temperature setting.
- **Stage 1, data foundation (done):** `sources.py` loads the JSON (dropping 5 duplicate URLs, 268 remain), cleans scraped text (links to anchor text, navigation, consent banners, images and repeated menu lines removed; about 64% of the text is kept), derives publication dates with the ordered rules above, and applies the recency filter: 104 of 268 sources pass. `uv run briefing dates` audits every decision. The cutoff boundary (2025-04-05 excluded, 2025-04-06 included), every date rule, cleaning and the real data file are covered by tests (124 in the suite). Writing the tests exposed a flaw in the first cleaning rule, which deleted genuine sentences that mentioned "cookies", so the boilerplate rule now has two tiers.
- **Stage 2, taxonomy and personas (done):** `topics.yaml` (the 11 topics from the task, each with a description written to be embedded) and `personas.yaml` (the two personas), loaded and validated by `briefing.topics`, plus `uv run briefing topics`. Descriptions never mention a persona, which a test enforces; that test caught a "founders" in one description. `government-policy-updates` is scoped to health policy on purpose, so unrelated EU and education policy pages are not tagged with it. 153 tests in the suite now.
- **Stage 3, embeddings and tagging (code done, calibration pending):** `embeddings.py` (OpenAI embedder behind a small interface, content-hash disk cache, cached wrapper with hit and miss counts, truncation to the embedding limit) and `tagging.py` (cosine similarity, multi-label tagging with threshold and cap), plus `uv run briefing tags` to calibrate the threshold from real scores. Everything is tested with fake embedders and a fake OpenAI client (177 tests in the suite). The live run is yours to do; its error output never includes provider messages, which can echo key fragments.
- **Stage 4, retrieval (done offline):** `retrieval.py` tags the corpus, selects a persona's top-k sources from the tags (best score among the persona's topics, ties by URL, a per-topic minimum so one topic cannot crowd out the others), splits the chosen sources into passages, and keeps only the passages that match a persona topic above `PASSAGE_THRESHOLD`, giving each a citable id (`s2p3`) and its best topic. Sources with no relevant passage are dropped. Tested on synthetic vectors and on the real data (splitting loses no text and respects the size limits). `PASSAGE_THRESHOLD` and `MAX_PASSAGES_PER_SOURCE` are placeholders until calibrated with a working key. 209 tests in the suite.
- **Stage 5, generation (done offline):** `generation.py` builds the prompt (fixed rules: use only the passages, treat passage text as untrusted data and ignore instructions in it, write only about the reader's topics, cite passage ids, no links), asks the model for structured JSON (sections by topic, bullets, passage ids) through a `Generator` interface (`OpenAIGenerator` uses the Responses API and sends no sampling parameters), and `rendering.py` checks the answer and renders the Markdown. Validation removes citations to unknown passages and drops any bullet with no valid citation, no cited passage on its section's topic, empty text, or an unknown section. Bullet text is reduced to plain prose (URLs, `[n]` markers and Markdown or HTML stripped or escaped), every link in the output comes from the source table, citations are numbered in order of first use, and a final scan fails the briefing if it contains any URL that is not a selected source. No relevant passages gives a clear "no relevant recent sources" error, and an answer with nothing traceable is an error too. All tested with a fake model (239 tests in the suite); nothing has been run against the real model yet.
- **Stage 6, API (done offline):** `service.py` (`BriefingService`: tags the corpus on the first briefing request, selects sources, retrieves passages, generates; keeps finished briefings in memory per persona, never caches failures, and a lock stops two first requests doing the work twice) and `api.py` (`create_app`, a factory that validates the settings, topics and personas at startup and loads the sources; `GET /health`, `/topics`, `/personas`, `/briefings/{persona_id}` as Markdown or `?format=json`). Every endpoint has a summary and documented error responses. OpenAI failures map to clean JSON errors (503 rate limit, timeout or unreachable; 502 for auth, other provider errors and unusable answers; 404 for an unknown persona or no relevant sources; 500 for bugs), and responses and logs never include provider messages. The OpenAI client is built with `OPENAI_TIMEOUT_SECONDS` and `OPENAI_MAX_RETRIES` (retries with backoff on rate limits, timeouts and server errors). Logging uses the standard `logging` module at `LOG_LEVEL`, with counts but never source text. `uv run briefing` now checks the settings and files before starting the server. Tested with fake models and a corpus built in the tests (268 tests in the suite).
- **Stage 7, frontend (done offline):** one static page served by FastAPI at `/` (`index.html`, `app.js`, `render.js`, `style.css`), with `marked` and `DOMPurify` vendored (no CDN). It lists the personas, fetches a briefing as JSON and renders its Markdown through DOMPurify with a strict allowlist (no images, styles or forms; `https://` links only, opened with `noopener`); error messages are inserted as text. The page and assets are served with a Content-Security-Policy of `'self'` only (no inline script or style), `nosniff` and no referrer, and the page uses no inline scripts, styles or handlers so the policy can be that strict. Checked in the real Edge browser (driven by a script, with fake models and a four-source corpus): personas load, each briefing renders with working citation links, the no-sources and offline cases show a message with a retry button, and an injected inline script is blocked by the policy. The real marked and DOMPurify were also run against 13 hostile inputs (script, handler, image, iframe, form, `javascript:` and `data:` links, encoded variants), and all were neutralised. Automated tests (283 in the suite) cover serving, headers, the page structure and the pinned hashes of the vendored files, and, in a real headless Chrome or Edge, the sanitiser itself (17 hostile inputs, link safety, a real briefing, a negative control that proves the checks can fail, and the page loading under its policy). Node alone cannot run DOMPurify (no DOM), so these use the browser; they skip when none is installed, and CI sets `REQUIRE_BROWSER` so a missing browser fails there.


## Future Work
- Check each article for data validity since the agentic coding model is non-deterministic
