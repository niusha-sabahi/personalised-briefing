# Executive Briefing

A FastAPI service that generates Markdown briefings, with cited sources, for different personas from a set of web sources. See [task.md](task.md) for the assignment and [REQUIREMENTS.md](REQUIREMENTS.md) for the full requirements.

## Features

- **Two personas out of the box:** a Healthcare Policy Analyst (USA) and a Tech Startup Founder (London). A persona is just a list of topics in a YAML file, so adding one needs no code change.
- **Relevant and recent:** briefings use only the supplied sources, only those published in the month before 6 May 2025, and only the passages that match the persona's topics.
- **Every claim cited:** each bullet links to its source, the Sources list names the title and site, and any citation the app cannot verify is dropped.
- **Organised by topic:** one section per topic the persona follows, with nothing off-topic.
- **Web page:** persona cards that show the topics each one follows, a loading spinner with a retry button, and a strip showing how many sources were used, their dates and when the briefing was prepared.
- **Document-style briefing:** readable serif text, small unobtrusive citation numbers and a banner with a logo.
- **Light and dark mode:** the page follows your device's light or dark setting.
- **Print or save as PDF:** use the browser's own print function (Ctrl+P, then "Save as PDF"). A print layout removes the banner and buttons, uses black on white, writes out each source's web address and keeps headings with their text, so the saved page reads as a clean document.
- **Safe by design:** the API key never appears in logs or responses, source text is treated as untrusted, the briefing is sanitised before display, and the page loads nothing from other sites.
- **API:** JSON or Markdown briefings, with interactive docs at `/docs`.
- **Quick repeats:** embeddings are cached on disk and finished briefings in memory.
- **Tested end to end:** hundreds of offline tests, opt-in live tests, and an Agent Skill that lets a coding agent set up, start and check the app.

## Setup (from a fresh clone)

These steps are written for Windows, macOS and Linux. They were tested on Windows.

**You need:**
- **Git** and access to this private repository (signed in to GitHub with a credential manager or a personal access token, or an SSH key).
- **uv**, the Python package manager ([install guide](https://docs.astral.sh/uv/getting-started/installation/)). On macOS and Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`. On Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`. Open a new terminal afterwards. uv downloads Python 3.12 itself, so you do not install Python.
- **An OpenAI API key** that can use the generation model and the embedding model.
- Optional: Chrome, Chromium or Edge, for the browser-based sanitiser tests (they are skipped without one).

**1. Clone and install.** The last command creates `.venv` and installs the locked dependencies.

```
git clone https://github.com/niusha-sabahi/personalised-briefing.git
cd personalised-briefing
uv sync
```

The input data (`sources_06-05-25.json`) is in the repository, so nothing else is downloaded.

**2. Add your settings.** Copy the example file and edit the copy (macOS and Linux: `cp .env.example .env`; Windows PowerShell: `Copy-Item .env.example .env`). Set `OPENAI_API_KEY` to your key. The two model names are already filled in as `GENERATION_MODEL=gpt-5.6-luna` and `EMBEDDING_MODEL=text-embedding-3-small`; change them only if your account uses other models. Every other option is optional and documented in [.env.example](.env.example). The settings file is gitignored, so your key is never committed.

**3. Check the install (free, no key needed).** The first command prints both personas and their topics. The second runs the offline test suite, which takes about a minute.

```
uv run briefing topics
uv run pytest
```

**4. Start the server.** It serves on http://127.0.0.1:8000.

```
uv run briefing
```

Open `http://127.0.0.1:8000/` in a browser and choose a persona. The first briefing request is slow, because it embeds the sources and passages and calls the generation model; it costs a few cents. The embeddings are cached in `.cache/embeddings`, so later runs are quicker, and repeat requests for the same persona are served from memory. Stop the server with Ctrl+C.

**5. Optional: run the Agent Skill.** The project includes an Agent Skill named `test-briefing-app` (its instructions are in [skills/test-briefing-app/SKILL.md](skills/test-briefing-app/SKILL.md)). It lets a coding agent set up, start and test the app. The skill's check script can also be run by hand: it starts the server, checks every endpoint and each persona's briefing, then stops the server. Stop your own server first, because the check uses the same port. It calls OpenAI, so it costs a few cents.

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

Start the server, which serves the API on `http://127.0.0.1:8000`. Then, from a second terminal, check that it is up:

```
uv run briefing
curl http://127.0.0.1:8000/health
```

Interactive API docs (the API reference) are at `http://127.0.0.1:8000/docs`. The server refuses to start if the settings or `topics.yaml` / `personas.yaml` are invalid. The endpoints, in the order of the commands below, return:

- the topic taxonomy;
- the persona ids and their topics;
- a Markdown briefing;
- a JSON briefing (the Markdown plus the cited sources).

```
curl http://127.0.0.1:8000/topics
curl http://127.0.0.1:8000/personas
curl http://127.0.0.1:8000/briefings/healthcare-policy-analyst
curl "http://127.0.0.1:8000/briefings/tech-founder?format=json"
```

The first briefing request embeds the sources (cached on disk) and calls the generation model, so it is slow and needs a working OpenAI key; later requests for the same persona are served from memory until the server restarts. Errors are JSON `{"detail": ...}`: 404 for an unknown persona or when no relevant recent sources exist, 503 when OpenAI is rate limiting or unreachable, 502 when OpenAI rejects the request or returns an unusable answer. They never include provider messages or stack traces. If OpenAI rejects a request, the server log shows only the error class and status; set `LOG_LEVEL=DEBUG` to also log the provider's message with key-like text masked, which says which parameter it objected to. 

### Topics and personas

Topics (`topics.yaml`) and personas (`personas.yaml`) are plain data. A persona is an id, a position, a location and a list of topic ids; to add one, add an entry (no code changes). Both files are validated when loaded (unique slug ids, no unknown fields, every persona topic must exist). To check them (the command reports whether the files are valid and which topics each persona follows):

```
uv run briefing topics
```

### Embeddings and topic tags

Each recent source (title plus cleaned text, truncated to 16,000 characters) and each topic description is embedded with `EMBEDDING_MODEL`. Vectors are cached on disk in `CACHE_PATH`, keyed by a hash of the model and the text, so a repeat run makes no API calls and changing one topic description re-embeds only that topic. A source is tagged with every topic whose cosine similarity is at or above `TAGGING_THRESHOLD`, up to `MAX_TAGS_PER_SOURCE`. The defaults (threshold 0.30, at most 4 tags) were calibrated on the real sources: unrelated pages score about 0.2 against a topic and on-topic pages 0.4 to 0.6, and the tags only build the candidate pool, so they favour recall while passage matching does the precise filtering. This command calls the OpenAI API (it needs your key in the local env file) and prints the score distribution to choose it from. 

The first command shows score quantiles, a threshold sweep and the top sources per topic. 
The second tries another threshold without changing the settings:

```
uv run briefing tags
uv run briefing tags --threshold 0.40
```

### Frontend

Open `http://127.0.0.1:8000/` for the web page. A banner gives the title and a one-line description. Personas are cards side by side (one per row on a narrow screen), each with an initials badge, the role, the location and the topics it follows (the first four, then "+n more"). They work as a radio group: Tab to the group, the arrow keys move between the cards, and Enter, Space or a click chooses one. Choosing one shows its briefing as a document (serif text, small raised citation numbers, a Sources list that names each site), with a spinner while it is prepared (the first one takes 10 to 20 seconds), a retry button if something fails, and a strip above it with the number of sources, the months they come from and when the briefing was prepared. The page prints cleanly (Ctrl+P, or "Save as PDF" in the print dialog): the banner and controls are hidden and each source's address is spelled out. It is one static page in `src/briefing/static/` with no build step, and it uses only system fonts. The briefing Markdown is rendered with [marked](https://github.com/markedjs/marked) and cleaned with [DOMPurify](https://github.com/cure53/DOMPurify) before it is inserted (only headings, paragraphs, lists, links and basic emphasis survive, and only `https://` links), and the page is served with a strict Content-Security-Policy that blocks inline script and any third-party request.

Both libraries are copied into `src/briefing/static/vendor/` (marked 18.1.1, DOMPurify 3.4.17), so the page loads nothing from a CDN and works offline. To upgrade one, download it into an empty directory with `npm pack marked@<version> dompurify@<version>`, copy `lib/marked.umd.js` and `dist/purify.min.js` (and the licence files) over the vendored copies, and update the pinned hashes in `tests/test_frontend.py`, which fail on any unplanned change.

### Calibrating the passage settings

`PASSAGE_THRESHOLD`, `MAX_PASSAGES_PER_TOPIC` and `MAX_PASSAGES_PER_SOURCE` decide which passages of the selected sources reach the model: each persona topic takes its best passages (at least the threshold) from across the sources, and no one source supplies more than the per-source limit. Page furniture (link lists, consent banners, legal footers, reference lists) is removed first. This report (it calls the OpenAI API for the passage embeddings, which are cached) shows, for each persona topic, how many passages clear each threshold and how many were chosen, then each selected source with its chosen passages, a few runners-up and how many passages were dropped as boilerplate. The commands below run it:

- for every persona;
- for one persona;
- with another passage threshold;
- without the recency preference.

```
uv run briefing passages
uv run briefing passages --persona tech-founder
uv run briefing passages --threshold 0.35
uv run briefing passages --recency-bonus 0
```

### Publication dates and the recency filter

The sources have no date field, so each date is derived (strongest rule first): a full date in the URL, a year-month in the URL (refined from the text when it has a date in that month), a "Published/Posted/Released" label, an "Updated/Last update" label, then the first date near the top of the text. Dates after 2025-05-06 are ignored, and sources with no determinable date are excluded. A source is kept if published on or after 2025-04-06 (`CUTOFF_DATE`). To audit the result for every source (no API key needed), the first command lists every source with KEEP or DROP, its date, the rule that found it and its URL. The second shows only the kept sources (use `--only excluded` for the others):

```
uv run briefing dates
uv run briefing dates --only kept
```

## Develop

The commands below, in order:

- format and lint (includes the docstring rules);
- type check;
- run the tests (the sanitiser tests need Chrome, Chromium or Edge, else they skip);
- run the opt-in live tests against OpenAI (a few cents, needs your key);
- run the Agent Skill's end-to-end check (live, a few cents);
- install the pre-commit hooks, once per clone (they run format, lint, type check and the tests on each commit);
- run the hooks on demand (needs Git 2.31 or newer).

```
uv run ruff format && uv run ruff check --fix
uv run mypy src
uv run pytest --cov
uv run pytest -m integration -v
uv run python skills/test-briefing-app/scripts/check_app.py --start
uv run pre-commit install
uv run pre-commit run --all-files
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

**Status:** all 40 requirements (20 Must, counting the four sub-requirements of M3, and 20 Should) in [REQUIREMENTS.md](REQUIREMENTS.md) are complete and verified. The code is in a private GitHub repository with CI green. The pipeline was tuned and checked against the real OpenAI models, and both personas' briefings were read and judged by hand five times.

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

- 390 offline tests that use fake models, so they need no key: unit tests for every stage, API tests, pinned hashes for the input data and the vendored libraries, and a real headless browser for the HTML sanitiser (with a negative control to prove the checks can fail).
- 3 opt-in live tests (`uv run pytest -m integration`) run the whole pipeline against OpenAI, check that every topic has tagged sources, and attempt a prompt injection.
- Ruff (with docstring rules), strict mypy, pre-commit and GitHub Actions CI all pass.

### What the live data changed

Calibrating on real scores and reading real briefings led to these decisions (details in the Calibration section above): a lower tagging threshold, two sources per topic, more passages per topic, a recency preference so dated news is not outranked by evergreen explainers, and prompt rules against speculation, promotion, writing about the publication itself, repeated developments and bullets that do not name their subject. One idea was tried and rejected: capping a source's passages per topic made the briefings thinner.

## Future Work

- **Custom personas from a description.** Let a user describe their interests in a sentence or two (for example "I run a climate-tech fund and follow carbon markets and grid storage") and have the AI generate the topics for a new persona, so defining one needs no knowledge of the taxonomy.
- **Option to download the brief as PDF** Allows the user to download the brief text as a PDF document, by a button on the brief page.
- **Briefing quality.** Known limitations from the live reads:
  - A company's own press-release claim (a self-reported accuracy figure) can pass as news.
  - The "state each development once" rule shortened the executive-order coverage, so some of its details are missing.
  - Product management is thin because the data has little on it.
  - Near-duplicate sources (a CDC report and its PDF) are not merged.
