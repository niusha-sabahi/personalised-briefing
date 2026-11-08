# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

A uv project with a `src/briefing/` package, ruff, mypy (strict) and pytest configured, a pre-commit hook (run `uv run pre-commit install` once per clone; it runs ruff format and check, mypy and the tests on every commit) and a CI workflow (written, not yet run on GitHub). Stages 0 to 9 are done (data, taxonomy, embeddings and tagging, retrieval, generation, API, frontend, hardening, Agent Skill in `skills/test-briefing-app/`); the pipeline is calibrated and verified against the real OpenAI models, and the skill passed its first live run. Delivery (private repo, push, fresh-clone check) remains. See [README.md](README.md) and REQUIREMENTS.md for progress.

Commands (all through uv; if `uv` is not on PATH, use `python -m uv`):
- `uv sync`: install into `.venv`.
- `uv run ruff format` and `uv run ruff check --fix`: format and lint (the `D` docstring rules are on).
- `uv run mypy src`: type check.
- `uv run pytest --cov`: full test suite (integration tests are excluded by default through `addopts`).
- `uv run pytest -m integration -v`: the opt-in live tests (a few cents; the user runs them, not you).
- `uv run briefing`: serve the API on http://127.0.0.1:8000 (needs the settings in `.env`; checks them and the topic and persona files first, then starts `briefing.api:create_app` as a uvicorn factory). Endpoints: `/` (the web page), `/health`, `/topics`, `/personas`, `/briefings/{persona_id}` (Markdown, or `?format=json`).
- `uv run briefing topics`: validate `topics.yaml` and `personas.yaml` and show which topics each persona follows (exits 1 with a message if invalid).
- `uv run briefing tags [--threshold X]`: embed the usable sources and topics (cached in `.cache/embeddings`) and print score quantiles, a threshold sweep and the top sources per topic, to calibrate `TAGGING_THRESHOLD`. Calls the OpenAI API, so the user runs it, not you.
- `uv run briefing passages [--persona ID] [--threshold X] [--recency-bonus X]`: for each persona, show per topic how many passages clear each threshold and how many were chosen, the selected sources with their chosen passages (and runners-up, and how many passages were dropped as boilerplate), to calibrate `PASSAGE_THRESHOLD`, `MAX_PASSAGES_PER_TOPIC` and `MAX_PASSAGES_PER_SOURCE`. Calls the OpenAI API, so the user runs it, not you.
- `uv run python skills/test-briefing-app/scripts/check_app.py [--start] [--persona ID]`: the Agent Skill's end-to-end check of a running server (live, a few cents; the user runs it).
- `uv run briefing dates [--only kept|excluded]`: audit the publication date, the rule that found it, and the keep/drop decision for every source. Re-run it after any change to cleaning or date rules and spot-check the output.

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

## Architecture and development stages

**Design.** An offline, cached *build* step and a *serve* step:
```
build:  sources.json -> load + dedupe -> clean -> extract date -> recency filter
        -> embed (cached) -> multi-label topic tags
serve:  persona topics -> select top-k tagged sources -> extract relevant passages
        -> LLM returns structured JSON -> render Markdown + validate citations
```
- Pure core (`sources`, `tagging`, `retrieval`, citation validation: no I/O). Only `embeddings` and `generation` talk to OpenAI, behind small interfaces that tests replace with fakes.
- Topics and personas are data (`topics.yaml`, `personas.yaml`), validated at startup. A persona is only a list of topic ids.
- Dates come from an ordered, auditable pipeline: URL path, then a labelled "Published" date in the text, then the first full date near the top of the text. Each result records which rule matched. Sources with no date are excluded (M4).
- The tagging threshold is calibrated from the real score distribution, not guessed.
- *Confirmed by the user:* (a) select relevant **passages** within the chosen sources and send only those to the model (M8), which extends M3.2 with passage embeddings for selected sources only (cached); (b) the model returns **structured JSON** (sections, bullets, passage ids) and our code renders the Markdown and the Sources list, so every citation maps to a real source (M7, S14). A bullet citing an unknown passage id is dropped.
- Frontend: one static page served by FastAPI, rendered with `marked` and sanitised with `DOMPurify` (S8), with no build step.

**Stage 1 result:** 273 entries become 268 unique URLs; 104 pass the recency filter (84 have no determinable date, the rest are older than 2025-04-06). Date rules, strongest first: full date in the URL, year-month in the URL (resolved to a day from the text when possible; a URL month beats a text label), "Published/Posted/Released" label, "Updated/Last update" label, first date near the top of the text. Dates after 2025-05-06 are ignored (events, deadlines). Slash dates (04/05/2025) are not supported because day-first and month-first are ambiguous. A month-only date inside the cutoff month (April 2025) is excluded because the day is unknown. "Published" is what M4 asks for, so a page published long ago but updated recently is judged by its published date when one is labelled.

**Stage 2 result:** `topics.yaml` holds exactly the 11 topics from the task (id, label, description; the description is what gets embedded) and `personas.yaml` holds the two personas as an id, position, location and `topic_ids`. Both are validated on load (`briefing.topics`): slug ids, unique ids, no unknown fields, every persona topic must exist, no repeats. Writing descriptions: they describe a subject area and must not mention a persona (a test enforces this). `government-policy-updates` is deliberately scoped to *health* policy, otherwise the EU urban and education policy pages in the data would be tagged with it and leak into the healthcare briefing. Adding a topic is a YAML change; changing a description re-embeds only that topic (stage 3).

**Data facts that shape the design** (checked 2026-11-06): 273 sources, 5 duplicate URLs; median text about 15k characters, max 375k (so truncate or chunk before embedding); only 39 URLs carry a date, 157 sources have a full date near the top of the text, and 47 have no date anywhere (excluded by M4); topics are mixed (education, EU policy, drugs.com and others), so most sources will stay untagged.

**Stage 3 result:** `embeddings.py` has an `Embedder` protocol, `OpenAIEmbedder` (batches of 16, results re-sorted by index), `EmbeddingCache` (one JSON file per text, keyed by sha256 of model and text, atomic writes, corrupt files count as misses) and `CachedEmbedder` (hit and miss counters, duplicate texts embedded once). A source is embedded as its title plus cleaned text truncated to 16,000 characters; a topic as its description. `tagging.py` is pure: `similarity_matrix` (cosine) and `tag_sources` (score >= threshold, strongest first, ties by topic id, capped). The cache key is the content hash and model, not the URL, so identical text is shared and an edited source is re-embedded. Calibrated with the real key from `briefing tags` (104 sources): unrelated sources score about 0.2, on-topic 0.4 to 0.6; the defaults are threshold 0.30 and at most 4 tags per source (was 0.35 and 3, which starved venture capital and health-equity). Tagging favours recall because passage matching does the precise filtering. Every required topic has tagged sources; venture capital and product management have the fewest.

**Stage 4 result:** `retrieval.py`. `tag_corpus` embeds and tags every usable source. `select_sources` (pure) keeps candidates that carry a persona topic, ranks by best persona-topic score (ties by URL) and gives each persona topic up to `per_topic_min` sources, in rounds (every topic gets its first before any gets its second; sources taken to fill a topic count for it in later rounds): a chosen source counts only for the topic it matches best (its primary topic), so a weak mention cannot satisfy a minimum, and a topic short of primary sources takes its best-scoring carriers; if minimums exceed `top_k`, earlier persona topics win; the rest is filled to `top_k` by overall rank. `split_passages` cuts cleaned text into 200 to 1200 character passages (tests check no text is lost on the real data). `is_boilerplate` drops link lists (URL characters over 15% of the passage, or two leftover `](http` fragments), consent and legal page furniture (a regex of phrases, deliberately without generic words such as copyright; two hits, or one in a passage under 300 characters) and numbered reference entries; the junk found in the first live report is a test fixture, and a sanity band (5% to 40% of passages) guards against over-filtering. Dropped before embedding, so it costs nothing. `gather_candidates` scores every remaining passage of the selected sources against every persona topic. `choose_passages` (pure) lets topics take turns (persona order within a round) picking their best remaining passage at or above `PASSAGE_THRESHOLD`, up to `per_topic` each and `per_source` per source; a passage serves one topic; this is why a funding passage inside an AI article appears under funding. `gather_candidates` marks a passage `recent` when it states a full date inside the recency window (cutoff to latest, via `dates_in_text`, which ignores dates after the latest because they are events), and `choose_passages` adds `recency_bonus` (default 0.15) to such a passage's score for ranking only (qualifying by the threshold and the reported score stay raw), because evergreen explainers outscored dated news by 0.1 to 0.2 on topic similarity and the AI news page never reached the model. 0.15 was calibrated offline from the cached embeddings with a throwaway script and a stub embedder that raises on any API call (so no key is involved): at 0.22 the weakest dated pick fell to 0.41, barely above the threshold. `build_context` returns the kept sources and `Passage`s with ids like `s2p3` (a source with no chosen passage is dropped, so ids are numbered after dropping), each with the topic it was chosen for. Defaults after two live calibration rounds: `top_k` 10 and `per_topic_min` 2 (a single source per topic let a source that merely mentioned venture capital stand in for it, and the London-relevant VC and funding sources were never selected), passage threshold 0.40 (0.30 kept 85% of passages and filtered nothing), 7 per topic and 5 per source (they were 3 and 3 until the first live briefings: passages are chosen for being about a topic, which favours background over news, so the model needs more to choose from, and it ignores junk well). `per_source_per_topic` (optional, default None) caps one source's passages for one topic; at 2 it made both live briefings thinner (a source's strongest passage was pushed to another topic, the KFF statistics dropped out) and did not bring in the AI news page, so it is off, and kept only because it is small and tested; backfilling is not needed (no selected source was left empty at 0.30 or 0.40). The `public-health-data` topic description no longer names MMWR or the CDC, because footers repeating those names outscored real content.

**Stage 5 result:** `generation.py`: `SYSTEM_PROMPT` (fixed rules, eight of them; rule 5 asks for specific recent developments with dates, figures and names over general background, rule 1 forbids speculation about relevance ("may support") and says to leave out a passage that does not address a section's topic, rule 4 says to state each development once, under the section it fits best, rule 8 forbids referring to "the passages" and writing about a publication itself, and rule 3 treats a company describing its own products as promotion unless it reports a concrete development; all added after reading the first live briefings), `build_prompt` (reader, topic ids, passages in `<passage id topic>` blocks with `<` escaped), `Generator` protocol, `OpenAIGenerator` (Responses API `responses.parse` with `BriefingDraft`, `store=False`, no sampling parameters, error if unparsed), `generate_briefing` (raises `NoRelevantSourcesError` before any model call when there are no passages; `GenerationError` when nothing survives validation or a stray URL is found). `rendering.py` (pure): `validate_draft` (unknown ids removed; a bullet is dropped without a valid citation, without a cited passage on its section's topic, with empty text, or in an unknown section; sections in persona order), `plain_text` and `_escape` (model text can never carry links, headings, lists or HTML), `render_markdown` (citations `[n]` link to the source table, numbered by first citation, only cited sources listed), `foreign_urls` (final guard, S14). Draft and result models are in `models.py`. The same-topic citation rule is strict; live runs dropped at most one bullet per briefing, so it stays.

**Stage 6 result:** `service.py` (`BriefingService.from_settings` loads and cleans the sources; the first `briefing_for` call tags the corpus and the result is kept; briefings are cached per persona in memory, failures are not cached, one lock serialises generation; `make_openai_client` sets the timeout and retries from settings, `make_embedder` adds the disk cache) and `api.py` (`create_app(settings=None, *, embedder=None, generator=None)` is the app factory, so tests inject fakes and there is no module-level `app`; startup raises `TaxonomyError` on bad data files). Error mapping lives in one table (`_ERROR_MAP`): `NoRelevantSourcesError` 404, `GenerationError` 502, rate limit and connection or timeout 503, auth, permission and other OpenAI errors 502, anything else 500; handlers log the exception class and provider status only, never the message. An unknown persona is a 404 that lists the known ids. The shared test fixtures are in `tests/conftest.py` (a four-source corpus, a three-topic taxonomy, `KeywordEmbedder`, and `EchoGenerator`, which cites every passage in the prompt); API tests build the app with them and need no key.

**Stage 7 result:** `src/briefing/static/` holds the page (`index.html`, `app.js`, `render.js`, `style.css`) and `vendor/` (`marked.umd.js` 18.1.1 and `purify.min.js` 3.4.17 from the npm registry via `npm pack`, plus their licences). The user chose vendoring over a CDN and does not want a CDN fallback: if a library cannot be vendored, stop and ask. `api.py` serves `/` and `/static`, adds a Content-Security-Policy of `'self'` (no inline script or style, no third-party connections), `nosniff` and `Referrer-Policy: no-referrer` to those paths only (not `/docs` or the JSON API), and registers `.js` as `text/javascript` because Windows can map it to `text/plain`, which `nosniff` would turn into blocked scripts. `render.js` is the one place briefing HTML is made: `marked.parse`, then `DOMPurify.sanitize` with tags limited to headings, paragraphs, lists, links, `strong`, `em`, `code` and `br`, attribute `href` only, `https://` URLs only, links forced to `target=_blank rel="noopener noreferrer"`; it throws if DOMPurify has no DOM, because DOMPurify would otherwise return the input unchanged. `app.js` has exactly one `innerHTML` (the sanitised briefing); messages use `textContent`. Tests (`tests/test_frontend.py`) check serving, headers, no inline script, style or handlers in the page, content types, the pinned SHA-256 of the vendored files and their licences. The sanitiser is tested in a real headless browser (`tests/test_frontend_browser.py`, user's choice over jsdom, which would add an npm dependency): Chrome, Chromium or Edge is found on the machine and run with `--dump-dom` and a throwaway profile; `tests/frontend_harness/` (test-only, not shipped) renders cases through the real `render.js` and the vendored libraries. It checks 17 hostile inputs, that every link is `_blank` with `noopener noreferrer`, a realistic briefing, a negative control (`&unsafe=1` skips DOMPurify and the same checks must then flag the output), and that the page runs under its policy and lists the personas from a live uvicorn server. The tests skip without a browser unless `REQUIRE_BROWSER` is set, which CI sets (the runner image ships Chrome; CI has not run yet). Never weaken `render.js` to check that tests fail, use the negative control instead.

**Stage 8 result:** `api.py` masks the configured key by exact value (`mask_secrets(text, secrets)`, secrets taken from `Settings`) as well as key-shaped text and bearer tokens, in the DEBUG provider detail and in the logged traceback of unexpected errors (logged as masked text, not `exc_info`, because the traceback's last line could hold the key). `tests/test_data_integrity.py` pins the SHA-256 of the input file (line endings normalised) and checks its shape, de-duplication and the recency invariants. `tests/test_integration.py` holds the three live tests (briefing validity per persona, every topic tagged, prompt injection through hostile passages built by hand and sent to the real model). They are marked `integration`, excluded by default (`addopts = "-ra -m 'not integration'"`), skip when `Settings()` cannot load, and the autouse settings-isolation fixture leaves them alone so they see the real settings. A key-leak search over all commits used the pattern `(^|[^A-Za-z0-9])sk-(proj-|svcacct-|live-|test-)?[A-Za-z0-9_-]{20,}` and printed file names only. The bare pattern `sk-` followed by 20 characters matches the input file 21 times inside words such as `risk-`, so the word boundary matters. Repeat the history search just before the push (stage 10). Prompt rule 5 now also says each bullet must stand alone and name what it is about.

**Stages.** Work in this order. Each stage ends with the quality gate green, requirement statuses updated in REQUIREMENTS.md, and the README updated. Update the Status column below as stages finish.

| # | Stage | Requirements | Status |
|---|---|---|---|
| 0 | Scaffold, tooling, hooks | M12, S2, S3, S5, S6 | Done |
| 1 | Data foundation: load, dedupe, clean, date extraction, recency filter, dates audit report (no API needed; riskiest, so first) | M2, M4, S10, part of S16 | Done (M4 complete; truncating or chunking text to the embedding limit, part of S10, moves to stage 3) |
| 2 | Taxonomy and personas: YAML files and validation (independent of stage 1) | M3.1, part of S9, S16, S18 | Done (M3.1 complete; serving the taxonomy over the API is stage 6) |
| 3 | Embeddings, disk cache, tagging, threshold calibration (first live API calls) | M3.2, M3.3, S11, S12 | Done (live `briefing tags` run, threshold 0.30 and cap 4 chosen) |
| 4 | Retrieval: persona selection and passage extraction (pure logic) | M3.4, part of M8 | Done (M3.4 complete; recalibrated from the first live `briefing passages` report; confirmed live that every persona topic gets passages) |
| 5 | Generation: prompt, structured output, rendering, citation validation, injection defence | M5, M6, M7, M8, S8, S13, S14 | Done offline with a fake model (M6, M7, S14 complete; M5, M8 and the prompt's quality need the live model) |
| 6 | API: endpoints, in-memory cache, error mapping, logging | M9, S9, S13, S15, S17 | Done offline (all five complete; live latency is 10 to 19 s per briefing against the 60 s timeout) |
| 7 | Frontend | M10, S8 | Done offline (both complete; sanitiser tested in a real headless browser) |
| 8 | Hardening: live integration test, data-integrity tests, CI and pre-commit verified, key-leak check | S18, S19, S4, S7, M11 | Done (S7, M11, S18 and S19 complete; the user's live run of `pytest -m integration` passed all 3 tests in 48 s; S4 waits for CI to run on GitHub) |
| 9 | Agent Skill | M15 | Done (M15 complete: tested against a fake-model server, and the user's live run of `check_app.py --start` passed all 9 checks) |
| 10 | Delivery: private repo, push, fresh-clone check; then optional C items (Docker, task aliases) | M14, M16, S20, C1, C5 | In progress (history key search clean, tracked files audited, and a fresh local clone passed setup, `briefing topics`, lint, type check and all 369 tests, so M14 is complete; the repo is on GitHub and CI is green, so S4 is complete; the push of the last commits and the final check of M16 remain) |

**Decisions made**
- Generation model id is `gpt-5.6-luna` (confirmed by the user). It has **no temperature setting**: never send `temperature` (or other sampling parameters) to it. Keep generation deterministic by other means (structured output, fixed prompts, stable ordering), and make any generation parameter optional in config.
- The user handles API-key and live-API setup. You never read the key (see Secrets); the first live embedding build in stage 3 is run by the user.

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

## Handoffs to the user

You cannot edit or read `.env` or the other protected files, and you cannot run live API commands. When a change you make will need the user to edit such a file or supply something from it (a new setting in `.env`, a key, a value, a live run), say so in the same reply, before they run anything and before the error can happen. Give the exact lines to add and where, and keep this in the closing message of the change. Do not leave them to discover it from an error.

## Environment notes

- Windows with PowerShell; the Bash tool is also available.
