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

The first briefing request embeds the sources (cached on disk) and calls the generation model, so it is slow and needs a working OpenAI key; later requests for the same persona are served from memory until the server restarts. Errors are JSON `{"detail": ...}`: 404 for an unknown persona or when no relevant recent sources exist, 503 when OpenAI is rate limiting or unreachable, 502 when OpenAI rejects the request or returns an unusable answer. They never include provider messages or stack traces. If OpenAI rejects a request, the server log shows only the error class and status; set `LOG_LEVEL=DEBUG` to also log the provider's message with key-like text masked, which says which parameter it objected to. 

### Topics and personas

Topics (`topics.yaml`) and personas (`personas.yaml`) are plain data. A persona is an id, a position, a location and a list of topic ids; to add one, add an entry (no code changes). Both files are validated when loaded (unique slug ids, no unknown fields, every persona topic must exist). To check them:

```
uv run briefing topics                # valid? which topics does each persona follow?
```

### Embeddings and topic tags

Each recent source (title plus cleaned text, truncated to 16,000 characters) and each topic description is embedded with `EMBEDDING_MODEL`. Vectors are cached on disk in `CACHE_PATH`, keyed by a hash of the model and the text, so a repeat run makes no API calls and changing one topic description re-embeds only that topic. A source is tagged with every topic whose cosine similarity is at or above `TAGGING_THRESHOLD`, up to `MAX_TAGS_PER_SOURCE`. The defaults (threshold 0.30, at most 4 tags) were calibrated on the real sources: unrelated pages score about 0.2 against a topic and on-topic pages 0.4 to 0.6, and the tags only build the candidate pool, so they favour recall while passage matching does the precise filtering. This command calls the OpenAI API (it needs your key in the local env file) and prints the score distribution to choose it from:

```
uv run briefing tags                  # score quantiles, threshold sweep, top sources per topic
uv run briefing tags --threshold 0.40 # try another threshold without changing the settings
```

### Frontend

Open `http://127.0.0.1:8000/` for the web page: choose a persona and its briefing is shown, with a loading message (the first one is slow) and a retry button if something fails. It is one static page in `src/briefing/static/` with no build step. The briefing Markdown is rendered with [marked](https://github.com/markedjs/marked) and cleaned with [DOMPurify](https://github.com/cure53/DOMPurify) before it is inserted (only headings, paragraphs, lists, links and basic emphasis survive, and only `https://` links), and the page is served with a strict Content-Security-Policy that blocks inline script and any third-party request.

Both libraries are copied into `src/briefing/static/vendor/` (marked 18.1.1, DOMPurify 3.4.17), so the page loads nothing from a CDN and works offline. To upgrade one, download it into an empty directory with `npm pack marked@<version> dompurify@<version>`, copy `lib/marked.umd.js` and `dist/purify.min.js` (and the licence files) over the vendored copies, and update the pinned hashes in `tests/test_frontend.py`, which fail on any unplanned change.

### Calibrating the passage settings

`PASSAGE_THRESHOLD`, `MAX_PASSAGES_PER_TOPIC` and `MAX_PASSAGES_PER_SOURCE` decide which passages of the selected sources reach the model: each persona topic takes its best passages (at least the threshold) from across the sources, and no one source supplies more than the per-source limit. Page furniture (link lists, consent banners, legal footers, reference lists) is removed first. This report (it calls the OpenAI API for the passage embeddings, which are cached) shows, for each persona topic, how many passages clear each threshold and how many were chosen, then each selected source with its chosen passages, a few runners-up and how many passages were dropped as boilerplate:

```
uv run briefing passages                                  # every persona
uv run briefing passages --persona tech-founder           # one persona
uv run briefing passages --threshold 0.35                 # try another passage threshold
uv run briefing passages --recency-bonus 0               # see the selection without the recency preference
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
uv run pytest --cov                             # tests (the sanitiser tests need Chrome, Chromium or Edge, else they skip)
uv run pytest -m integration -v                 # opt-in live tests against OpenAI: a few cents, needs your key
uv run python skills/test-briefing-app/scripts/check_app.py --start   # the Agent Skill's end-to-end check (live, a few cents)
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

## Calibration

The retrieval settings were set from real data with the live API, and are documented in `.env.example` and `config.py`. The reasons:

- **Tagging** (`TAGGING_THRESHOLD` 0.30, `MAX_TAGS_PER_SOURCE` 4): unrelated pages score about 0.2 against a topic and on-topic pages 0.4 to 0.6. The earlier 0.35 and 3 starved venture capital and health equity. Tagging only builds the candidate pool, so it favours recall.
- **Source selection** (`TOP_K` 10, `PER_TOPIC_MIN` 2): with one source per topic, a page that merely mentioned venture capital stood in for it.
- **Passages** (`PASSAGE_THRESHOLD` 0.40, 7 per topic, 5 per source): 0.30 filtered nothing. Passages are chosen for being about a topic, which favours background over news, so the model needs more to choose from.
- **Recency** (`RECENCY_BONUS` 0.15): a passage that states a date inside the window ranks higher, because explainers outscored dated news by 0.1 to 0.2. At 0.22 the weakest dated pick barely cleared the threshold.
- **Tried and rejected:** capping one source's passages per topic (`MAX_PASSAGES_PER_SOURCE_PER_TOPIC`) made both briefings thinner and did not help, so it is off. Backfilling dropped sources was not needed.
- **Prompt:** eight rules, each added after reading real briefings (no speculation, no promotion, no writing about the publication itself, state each development once, bullets that stand alone). Every wording that failed live was replaced.
- **Result:** both briefings were read five times, then tuning stopped. In the last runs at most one bullet per briefing was dropped by validation. Generation takes 10 to 19 seconds per persona, inside the 60 second timeout. The browser console shows no Content-Security-Policy violations, and the live tests and the Agent Skill's check pass.

## Work completed

Status: stages 0 to 9 are done. The pipeline, API and page work against the real OpenAI models (live calibration, two briefings read five times, 3 live tests passing). The Agent Skill is written and its live run passed all 9 checks. Delivery is in progress: the repository is on GitHub (private), CI is green, and the local pre-push audit and a fresh-clone check passed; the final push of the last commits remains.

- **Assignment analysis:** reviewed `task.md` and inspected `sources_06-05-25.json` (273 web sources, fields `url`, `title`, `description`, `text`, and no date field).
- **Requirements:** wrote [REQUIREMENTS.md](REQUIREMENTS.md), a tiered list (Must / Should / Could) that is deterministic and testable. Key design decisions:
  - Sources are embedded and tagged by **topic** (multi-label), not by persona, so new personas only need a new topic list.
  - All 11 interests from the task are in the topic taxonomy, and extra topics are allowed.
  - Briefings contain only the passages relevant to the persona, cited to a source.
  - Recency cutoff of 2025-04-06, one month before the newest source.
  - uv project with a `.venv`, delivered as a single private GitHub repository, with an agent-neutral skill in `skills/`.
- **Repository guidance:** wrote [CLAUDE.md](CLAUDE.md) for coding agents, covering the assignment, the data format, secrets handling and protected files.
- **File protection:** `.env`, `sources_06-05-25.json` and `task.md` can never be edited or deleted, and the protection files are covered too. It uses deny rules in [.claude/settings.json](.claude/settings.json) and a `PreToolUse` hook in [.claude/hooks/protect_files.py](.claude/hooks/protect_files.py). Both layers were verified: the hook script against 44 simulated tool calls (all passed, including fail-closed on bad input), and in a live session (file edits rejected by the deny rules, mutating shell commands blocked by the hook, read-only access still allowed). Shell matching is best-effort.
- **Requirement tracking:** every requirement in [REQUIREMENTS.md](REQUIREMENTS.md) now has a status marker (`[ ]` not started, `[~]` in progress, `[x]` complete and verified). Current tally: 35 of 46 complete (M: 19/20, S: 16/20, C: 0/6; M includes the sub-requirements M3.1 to M3.4).
- **Session rule:** [CLAUDE.md](CLAUDE.md) now requires each development session to keep the statuses current, check for regressions (tests, lint and type check once they exist) before finishing, and end with a summary of the requirements completed, unfinished, or regressed.
- **Project scaffold:** uv project (Python 3.12, `uv.lock`) with a `src/briefing/` package split into the modules planned in S1, a `briefing` script entry point, a working `/health` endpoint, and `Settings` (pydantic-settings, `SecretStr` key, model names and tuning in config). Ruff (with docstring rules), mypy strict and pytest with coverage are configured and pass; pre-commit and a GitHub Actions workflow are written but not yet exercised. Ruff skips `.claude/`, which is tooling and protected.
- **Quality-gate hook:** a `Stop` hook ([.claude/hooks/quality_gate.py](.claude/hooks/quality_gate.py)) runs ruff format, ruff check, mypy and the tests at the end of every agent turn and blocks finishing until they pass (no-op until tests exist, gives up after 3 failed attempts). The file-protection hook was also fixed so `.env.example` and `git commit -m` message text no longer cause false blocks, while `.env` stays fully protected. Both hooks have tests in `tests/`.
- **Passage calibration report:** `uv run briefing passages [--persona ID] [--threshold X]` (`reports.py`) prints, per persona, the selected sources, their best passages with the kept ones marked, a sweep of passage thresholds, and how many selected sources would end with no passage. `briefing tags` and `briefing passages` now share one runner that turns setup and OpenAI failures into a short message without provider text.
- **First live briefing (analyst):** with the real key, the server tagged the 104 sources from the embedding cache in about a second, chose 10 sources and 18 passages, and `gpt-5.6-luna` returned a valid structured briefing in about 10 seconds: six topic sections, 11 bullets citing 7 sources, 0 bullets and 0 citations dropped, and the page rendered it. The model ignored the junk passages (the navigation menu and the telemedicine association's marketing line), which the prompt tells it to.
- **First live briefing (founder):** 10 sources selected, 7 kept with 15 passages, a valid briefing in about 7 seconds with 0 bullets and 0 citations dropped, and every one of the 7 cited sources matching its section. This completes the first live read of both personas.
- **Tests on every commit:** the pre-commit config now also runs the test suite (without the opt-in live-API test), so a commit is checked by ruff format, ruff check, mypy and pytest. Verified on explicit files; `pre-commit run --all-files` needs Git 2.31 or newer.
- **Secret-reading protection:** CLAUDE.md now forbids reading secret values, and this is enforced two ways: a `Read(.env)` deny rule in `.claude/settings.json`, and the protect hook, which now also covers the Read and Grep tools, shell commands that read `.env` or `.env.*`, and printing secret environment variables (`.env.example` stays readable). Verified live with a decoy file: Read, `cat`, `echo $VAR` and `Get-ChildItem Env:` were all blocked. The hook tests cover these cases too.
- **Documentation rule:** [CLAUDE.md](CLAUDE.md) now requires, after every prompt, a README update and code documented through Google-style docstrings and why-comments only. Ruff's `D` rules will enforce docstrings (S3), and a new requirement S20 covers the README architecture overview and the OpenAPI docs.
- **Development plan:** [CLAUDE.md](CLAUDE.md) now holds the architecture, a data-driven summary of what the sources look like, and an 11-stage plan (data foundation first, then taxonomy, embeddings and tagging, retrieval, generation, API, frontend, hardening, Agent Skill, delivery) with a status column. Confirmed: the generation model is `gpt-5.6-luna` and it takes no temperature setting.
- **Stage 1, data foundation (done):** `sources.py` loads the JSON (dropping 5 duplicate URLs, 268 remain), cleans scraped text (links to anchor text, navigation, consent banners, images and repeated menu lines removed; about 64% of the text is kept), derives publication dates with the ordered rules above, and applies the recency filter: 104 of 268 sources pass. `uv run briefing dates` audits every decision. The cutoff boundary (2025-04-05 excluded, 2025-04-06 included), every date rule, cleaning and the real data file are covered by tests (124 in the suite). Writing the tests exposed a flaw in the first cleaning rule, which deleted genuine sentences that mentioned "cookies", so the boilerplate rule now has two tiers.
- **Stage 2, taxonomy and personas (done):** `topics.yaml` (the 11 topics from the task, each with a description written to be embedded) and `personas.yaml` (the two personas), loaded and validated by `briefing.topics`, plus `uv run briefing topics`. Descriptions never mention a persona, which a test enforces; that test caught a "founders" in one description. `government-policy-updates` is scoped to health policy on purpose, so unrelated EU and education policy pages are not tagged with it. 153 tests in the suite now.
- **Stage 3, embeddings and tagging (done, calibrated live):** `embeddings.py` (OpenAI embedder behind a small interface, content-hash disk cache, cached wrapper with hit and miss counts, truncation to the embedding limit) and `tagging.py` (cosine similarity, multi-label tagging with threshold and cap), plus `uv run briefing tags` to calibrate the threshold from real scores. Everything is tested with fake embedders and a fake OpenAI client (177 tests in the suite). The live run with the real key embedded all 104 recent sources and 11 topics (cached afterwards), and the tagging defaults were set from its score distribution: threshold 0.30 and at most 4 tags per source. Error output never includes provider messages, which can echo key fragments.
- **Stage 4, retrieval (done, recalibrated on live data):** `retrieval.py` tags the corpus, selects a persona's top-k sources from the tags (best score among the persona's topics, ties by URL, and a per-topic minimum where a source counts only for the topic it matches best, so a source that merely mentions a topic cannot stand in for it), splits the chosen sources into passages, drops boilerplate passages (link lists, consent banners, legal footers, reference entries) before embedding, and chooses passages per topic: each persona topic takes its best passages above `PASSAGE_THRESHOLD` (0.40) across the sources, topics taking turns so a dominant topic cannot crowd out the rest, at most `MAX_PASSAGES_PER_TOPIC` (7) per topic and `MAX_PASSAGES_PER_SOURCE` (5) per source (raised from 3 and 3 in two steps after the first live briefings, because passages are picked for being about a topic, which favours background over news). Each passage gets a citable id (`s2p3`) and the topic it was chosen for. Sources with no chosen passage are dropped. Tested on synthetic vectors and on the real data (splitting loses no text, the boilerplate rules catch the real junk seen in the first live report and keep real content). These changes came from the first live `briefing passages` report, which showed boilerplate taking the top passages (reference lists, disclaimers, related-link lists), no passages for health-equity (analyst) or venture capital and startup funding (founder) because each passage was assigned only to its single best topic, and a per-topic minimum met by weak mentions. A fourth round added a recency preference: a passage that itself states a date inside the recency window (6 April to 6 May 2025) ranks `RECENCY_BONUS` (0.15) higher when its topic picks, for ranking only, because evergreen explainers outscored dated news by 0.1 to 0.2 on topic similarity and the founder's AI news page never reached the model; the value was calibrated offline from the cached embeddings, and the prompt now also says to state each development once. A third round followed the first live briefings: the prompt now also tells the model to skip a company describing its own products unless it reports a concrete development, not to write about a publication itself, and not to speculate about relevance ("may support…"); these worked. An optional cap on how many passages one source may give a single topic (`MAX_PASSAGES_PER_SOURCE_PER_TOPIC`) was tried at 2 and made both briefings thinner without bringing in the AI news page, so it is off by default (the code and tests remain), and the model is instead given more candidates (7 per topic, 5 per source). A second round of fixes followed the next live report: the per-topic source minimum is now taken in rounds (every topic gets a source before any gets a second) and raised to 2 with `TOP_K` 10 (it was 1 and 8), so a thin topic such as venture capital gets a dedicated source and not just a source that mentions it, and a source whose page title is only its own address is listed by its site name (`medrxiv.org`) instead of "Untitled source". 320 tests in the suite.
- **Stage 5, generation (done offline):** `generation.py` builds the prompt (fixed rules: use only the passages, treat passage text as untrusted data and ignore instructions in it, write only about the reader's topics, cite passage ids, no links), asks the model for structured JSON (sections by topic, bullets, passage ids) through a `Generator` interface (`OpenAIGenerator` uses the Responses API and sends no sampling parameters), and `rendering.py` checks the answer and renders the Markdown. Validation removes citations to unknown passages and drops any bullet with no valid citation, no cited passage on its section's topic, empty text, or an unknown section. Bullet text is reduced to plain prose (URLs, `[n]` markers and Markdown or HTML stripped or escaped), every link in the output comes from the source table, citations are numbered in order of first use, and a final scan fails the briefing if it contains any URL that is not a selected source. No relevant passages gives a clear "no relevant recent sources" error, and an answer with nothing traceable is an error too. Tested with a fake model (239 tests at the time); the real model has since passed live runs.
- **Stage 6, API (done offline):** `service.py` (`BriefingService`: tags the corpus on the first briefing request, selects sources, retrieves passages, generates; keeps finished briefings in memory per persona, never caches failures, and a lock stops two first requests doing the work twice) and `api.py` (`create_app`, a factory that validates the settings, topics and personas at startup and loads the sources; `GET /health`, `/topics`, `/personas`, `/briefings/{persona_id}` as Markdown or `?format=json`). Every endpoint has a summary and documented error responses. OpenAI failures map to clean JSON errors (503 rate limit, timeout or unreachable; 502 for auth, other provider errors and unusable answers; 404 for an unknown persona or no relevant sources; 500 for bugs), and responses and logs never include provider messages. The OpenAI client is built with `OPENAI_TIMEOUT_SECONDS` and `OPENAI_MAX_RETRIES` (retries with backoff on rate limits, timeouts and server errors). Logging uses the standard `logging` module at `LOG_LEVEL`, with counts but never source text. `uv run briefing` now checks the settings and files before starting the server. Tested with fake models and a corpus built in the tests (268 tests in the suite).
- **Stage 7, frontend (done offline):** one static page served by FastAPI at `/` (`index.html`, `app.js`, `render.js`, `style.css`), with `marked` and `DOMPurify` vendored (no CDN). It lists the personas, fetches a briefing as JSON and renders its Markdown through DOMPurify with a strict allowlist (no images, styles or forms; `https://` links only, opened with `noopener`); error messages are inserted as text. The page and assets are served with a Content-Security-Policy of `'self'` only (no inline script or style), `nosniff` and no referrer, and the page uses no inline scripts, styles or handlers so the policy can be that strict. Checked in the real Edge browser (driven by a script, with fake models and a four-source corpus): personas load, each briefing renders with working citation links, the no-sources and offline cases show a message with a retry button, and an injected inline script is blocked by the policy. The real marked and DOMPurify were also run against 13 hostile inputs (script, handler, image, iframe, form, `javascript:` and `data:` links, encoded variants), and all were neutralised. Automated tests (283 in the suite) cover serving, headers, the page structure and the pinned hashes of the vendored files, and, in a real headless Chrome or Edge, the sanitiser itself (17 hostile inputs, link safety, a real briefing, a negative control that proves the checks can fail, and the page loading under its policy). Node alone cannot run DOMPurify (no DOM), so these use the browser; they skip when none is installed, and CI sets `REQUIRE_BROWSER` so a missing browser fails there.
- **Stage 8, hardening (done offline, live tests written):**
  - **Key handling.** The configured key is now masked by exact value, as well as by pattern, in every error log including tracebacks, so it is hidden even if it does not look like a key. Tests show it cannot appear in a response or in a log at DEBUG level during normal use or any failure. The whole git history (15 commits) and the working tree were searched for key-shaped strings, listing file names only, and there are none. The local settings file was never committed and is ignored.
  - **Data integrity.** Tests pin the input file by hash and check its shape, the de-duplication, and that no usable source predates the cutoff or lacks a date.
  - **Opt-in live tests** (`tests/test_integration.py`, `pytest -m integration`): a valid briefing for every persona, every topic tagged, and a prompt-injection check against the real model. Integration tests are now excluded by default (`addopts` in `pyproject.toml`), so a plain `pytest` never spends money.
  - **CI and pre-commit.** Every CI command (`uv lock --check`, `uv sync --locked`, format, lint, type check, tests) and the pre-commit hooks pass locally; CI has run on GitHub and is green (reported by the repository owner after the stage 8 push).
  - **Prompt.** Rule 5 says each bullet must stand alone: begin with the full name of the subject, repeat it in every bullet, never use a bare "the order" or "the report", with a worked example. The first wording failed live; the second worked on both personas.
  - 353 tests in the default run.
- **Agent Skill (stage 9):** [skills/test-briefing-app/](skills/test-briefing-app/SKILL.md) follows the agentskills.io format and is agent-neutral (plain `uv run` commands, paths inside the repo). It tells a coding agent to run the offline suite, check the settings without reading the key, then run `scripts/check_app.py`: a standard-library script that (with `--start`) starts the server and checks `/health`, `/topics`, `/personas`, the page and its security headers, the 404 for an unknown persona, and for each persona that the briefing has the right title and only that persona's topics as sections, a source link on every bullet, and only links that are in its numbered Sources list (exit 0 only if all pass). `tests/test_skill.py` checks the skill's format and that the commands it names exist, and runs the script against a live server with fake models (healthy, a persona with no sources, an unknown persona, no server).


## Future Work
- Check each article for data validity since the agentic coding model is non-deterministic
- Briefing quality, known limitations from the live reads: (1) bullets now name their subject (live-checked on both personas after the second wording of prompt rule 5; the first wording did not work); (2) a passage whose stated dates all fall before the recency cutoff (such as the November 2024 fellowship teaser on a May 2025 page) could be excluded or penalised, at the risk of losing evergreen background that mentions an old date; (3) a company's own press-release claim (a self-reported accuracy figure) can pass as news; (4) the "state each development once" rule shortened the executive-order coverage, so its details (the pill penalty timelines, the 780 manufacturers) are no longer all present; (5) product management is thin because the data has little on it; (6) near-duplicate sources (a CDC report and its PDF) are not merged.
