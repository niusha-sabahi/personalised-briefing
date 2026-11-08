# Personalised Briefing

A FastAPI service that generates Markdown briefings, with cited sources, for different personas from a set of web sources. See [task.md](task.md) for the assignment and [REQUIREMENTS.md](REQUIREMENTS.md) for the full requirements.

## Setup (from a fresh clone)

These steps are written for Windows, macOS and Linux. They were tested on Windows.

**You need:**
- **Git** and access to this private repository (signed in to GitHub with a credential manager or a personal access token, or an SSH key).
- **uv**, the Python package manager ([install guide](https://docs.astral.sh/uv/getting-started/installation/)). On macOS and Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`. On Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`. Open a new terminal afterwards. uv downloads Python 3.12 itself, so you do not install Python.
- **An OpenAI API key** that can use the generation model and the embedding model.
- Optional: Chrome, Chromium or Edge, for the browser-based sanitiser tests (they are skipped without one).

**1. Clone and install**

```
git clone https://github.com/niusha-sabahi/personalised-briefing.git
cd personalised-briefing
uv sync                      # creates .venv and installs the locked dependencies
```

The input data (`sources_06-05-25.json`) is in the repository, so nothing else is downloaded.

**2. Add your settings.** Copy the example file and edit the copy (macOS and Linux: `cp .env.example .env`; Windows PowerShell: `Copy-Item .env.example .env`). Set `OPENAI_API_KEY` to your key. The two model names are already filled in as `GENERATION_MODEL=gpt-5.6-luna` and `EMBEDDING_MODEL=text-embedding-3-small`; change them only if your account uses other models. Every other option is optional and documented in [.env.example](.env.example). The settings file is gitignored, so your key is never committed.

**3. Check the install (free, no key needed)**

```
uv run briefing topics       # prints both personas and their topics
uv run pytest                # the offline test suite, about a minute
```

**4. Start the server**

```
uv run briefing              # serves on http://127.0.0.1:8000
```

Open `http://127.0.0.1:8000/` in a browser and choose a persona. The first briefing request is slow, because it embeds the sources and passages and calls the generation model; it costs a few cents. The embeddings are cached in `.cache/embeddings`, so later runs are quicker, and repeat requests for the same persona are served from memory. Stop the server with Ctrl+C.

**5. Optional: check the running app end to end.** Stop the server first (the check starts its own on the same port):

```
uv run python skills/test-briefing-app/scripts/check_app.py --start
```

**If something goes wrong**

| Message or symptom | Cause and fix |
|---|---|
| `Invalid settings (NAME, ...). See .env.example.` | The named settings are missing or invalid in your settings file. Only the names are printed, never the values. |
| `uv: command not found` | Open a new terminal after installing uv, or check that its install folder is on your PATH. |
| Page shows an error, server log says `AuthenticationError 401` | The key is wrong, expired or has no access to the models. |
| 503 | OpenAI is rate limiting or unreachable. Wait and retry. |
| 404 for a persona | No recent source matched that persona's topics (or the persona id is unknown; the response lists the known ids). |
| Port 8000 already in use | Stop the other program using it. The port is fixed at 8000. |

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

**Status:** all 40 requirements (20 Must, 20 Should) in [REQUIREMENTS.md](REQUIREMENTS.md) are complete and verified. The code is in a private GitHub repository with CI green. The pipeline was tuned and checked against the real OpenAI models, and both personas' briefings were read and judged by hand five times.

### What was built

- **Data cleaning and dates.** The input has 273 entries and no date field. Duplicates are removed (268 URLs remain), scraped text is cleaned of navigation, consent banners and link lists, and each source gets a publication date from the first rule that matches (date in the URL, a "Published" label, then the first date near the top of the text). Sources with no determinable date, or dated before 2025-04-06, are excluded: 104 remain. `uv run briefing dates` shows the decision for every source.
- **Topics and personas as data.** The 11 topics from the task live in `topics.yaml` and the two personas in `personas.yaml`, each persona being only a list of topic ids. Both files are validated at startup, so adding a persona or topic needs no code change.
- **Embedding and tagging.** Sources and topic descriptions are embedded with OpenAI and cached on disk by content hash, so reruns cost nothing. A source is tagged with every topic it matches above a similarity threshold (0.30, at most 4 tags), calibrated from the real score distribution.
- **Retrieval.** For a persona, the best 10 sources are chosen with a guaranteed minimum per topic, so one topic cannot crowd out the rest. Their text is then split into passages, boilerplate is dropped, and each topic takes its best passages, with a small preference for passages that state a recent date.
- **Generation and citation checking.** `gpt-5.6-luna` receives only the chosen passages and returns structured JSON (sections, bullets, passage ids). The application, not the model, validates every citation and renders the Markdown and the numbered Sources list, so every link comes from the input file. Bullets without a valid on-topic citation are dropped, and a final scan rejects any stray URL. The prompt has eight rules, each added after reading real output.
- **API and web page.** FastAPI serves `/health`, `/topics`, `/personas` and `/briefings/{persona_id}`, with documented errors, retries and timeouts for OpenAI, and an in-memory cache. One static page renders the Markdown with vendored `marked` and `DOMPurify` under a strict Content-Security-Policy, with no CDN.
- **Agent Skill.** `skills/test-briefing-app/` lets a coding agent set up, start and test the app. Its check script verifies the endpoints, security headers and the structure and citations of each briefing.

### Security and safety

- The API key is a `SecretStr`, is masked in every log and error, and the whole git history was searched for leaks before the push.
- Source text is treated as untrusted: the prompt tells the model to ignore instructions inside it, a live test plants hostile instructions in passages and checks they are not followed, and model output is reduced to plain text before it is rendered.
- Development guards for the coding agent: hooks that protect the key file and the input data from edits (and the key file from being read), and a quality gate that runs format, lint, type check and tests before each session ends.

### Testing and quality

- 369 offline tests that use fake models, so they need no key: unit tests for every stage, API tests, pinned hashes for the input data and the vendored libraries, and a real headless browser for the HTML sanitiser (with a negative control to prove the checks can fail).
- 3 opt-in live tests (`uv run pytest -m integration`) run the whole pipeline against OpenAI, check that every topic has tagged sources, and attempt a prompt injection.
- Ruff (with docstring rules), strict mypy, pre-commit and GitHub Actions CI all pass.

### What the live data changed

Calibrating on real scores and reading real briefings led to these decisions (details in the Calibration section above): a lower tagging threshold, two sources per topic, more passages per topic, a recency preference so dated news is not outranked by evergreen explainers, and prompt rules against speculation, promotion, writing about the publication itself, repeated developments and bullets that do not name their subject. One idea was tried and rejected: capping a source's passages per topic made the briefings thinner.

## Future Work

- **Custom personas from a description.** Let a user describe their interests in a sentence or two (for example "I run a climate-tech fund and follow carbon markets and grid storage") and have the AI generate the topics for a new persona, so defining one needs no knowledge of the taxonomy. A sketch of how it would fit the current design:
- **Briefing quality.** Known limitations from the live reads:
  - A company's own press-release claim (a self-reported accuracy figure) can pass as news.
  - The "state each development once" rule shortened the executive-order coverage, so some of its details are missing.
  - Product management is thin because the data has little on it.
  - Near-duplicate sources (a CDC report and its PDF) are not merged.
