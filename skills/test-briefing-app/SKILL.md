---
name: test-briefing-app
description: Set up, start and test the personalised briefing generator (a FastAPI app that writes cited Markdown briefings for a persona). Use when asked to run, verify or debug this application, to check that its endpoints work, or to confirm that a briefing is valid, recent and correctly cited.
compatibility: Needs uv and Python 3.12, a shell opened at the repository root, and an OpenAI API key in the .env file (the offline checks need none).
---

# Test the briefing app

The app serves a briefing per persona at `http://127.0.0.1:8000`. A briefing is Markdown with one section per topic, a bullet per finding, and numbered links to the source pages. Run every command from the repository root.

## 1. Run the offline checks (no API key, free)

```
uv sync
uv run pytest
```

Expect every test to pass (the live tests are excluded by default). The tests use fake models, so this checks the code, not OpenAI. If it fails, fix that before going further.

Optional quality checks: `uv run ruff check`, `uv run mypy src`.

## 2. Check the settings

The live steps need a `.env` file at the repository root (copy `.env.example`; it lists every setting). It must hold `OPENAI_API_KEY`, `GENERATION_MODEL` and `EMBEDDING_MODEL`.

- Never print, log or paste the key, and do not read `.env`. If it is missing, ask the user to create it.
- `uv run briefing topics` validates `topics.yaml` and `personas.yaml` and needs no key. It exits 1 with a message when they are invalid.

## 3. Start the server and check it end to end

Live generation calls OpenAI and costs a few cents, about 10 to 15 seconds per persona the first time (repeats come from memory).

```
uv run python skills/test-briefing-app/scripts/check_app.py --start
```

`--start` runs `uv run briefing`, waits for `/health`, runs the checks and stops the server. Without `--start` the script checks a server that is already running (`--url http://host:port` to point elsewhere). `--persona healthcare-policy-analyst` limits the run to one persona and halves the cost.

The script prints one `PASS` or `FAIL` line per check and exits 0 only when all pass. It checks:

- `GET /health` answers, `/topics` and `/personas` are not empty.
- `GET /` serves the page with a Content-Security-Policy and `nosniff`.
- An unknown persona gives 404.
- For each persona, `GET /briefings/{id}?format=json` gives a briefing that:
  - starts with `# Briefing: <position>, <location>` and has a `Sources` section;
  - has only that persona's topics as section headings, and at least one;
  - has a source link on every bullet;
  - links only to URLs in its numbered Sources list, which matches the `sources` field;
- `GET /briefings/{id}` (no format) returns the same Markdown.

## 4. Optional: the live test suite

```
uv run pytest -m integration -v
```

This repeats the checks inside pytest and adds a prompt-injection test (hostile text hidden in source passages must not change the briefing) and a check that every topic has tagged sources. It costs a few cents.

## Manual checks

With the server running: `GET /docs` is the API reference, `GET /briefings/{persona_id}` returns Markdown, and `?format=json` returns `markdown`, `sources`, `dropped_bullets` and `dropped_citations`. A non-zero `dropped_bullets` means the model cited something invalid and the app removed it; occasional drops are normal, a high count is worth reporting.

## Reading failures

| Output | Likely cause |
|---|---|
| `no server answered` | Server not started, or a different port. |
| `status 404: ...` for a briefing | No recent source matched that persona's topics. |
| `status 502` or `503` | OpenAI error: bad key, wrong model name, rate limit or timeout. Check the server's console, which never prints the key. |
| `status 500` | A bug: read the server's console for the exception. |
| `bullet without a source link` or `link to a URL that is not a listed source` | Citation validation has regressed. This is a real defect. |
| `section ... is not one of the persona's topics` | The generated sections are not restricted to the persona's topics. This is a real defect. |

Report which checks failed with their output, and whether the offline suite passed.
