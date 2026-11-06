# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

The repo currently contains only the assignment ([task.md](task.md)), the input data, and a `.env`. No application code, dependencies, build, lint, or test tooling exists yet. Update this file (commands, architecture) as the implementation lands.

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

`.env` holds `OPENAI_API_KEY` and is gitignored. Never print or commit it. The `.gitignore` also covers `.venv/`, `__pycache__/` and `.idea/`.

## Environment notes

- Windows with PowerShell; the Bash tool is also available.
