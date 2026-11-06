# Personalised Briefing

A FastAPI service that generates Markdown briefings, with cited sources, for different personas from a set of web sources. See [task.md](task.md) for the assignment and [REQUIREMENTS.md](REQUIREMENTS.md) for the full requirements.

> Setup and run instructions will be added here once the application is implemented.

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

Status: planning and project setup are done. **The application itself is not implemented yet.**

- **Assignment analysis:** reviewed `task.md` and inspected `sources_06-05-25.json` (273 web sources, fields `url`, `title`, `description`, `text`, and no date field).
- **Requirements:** wrote [REQUIREMENTS.md](REQUIREMENTS.md), a tiered list (Must / Should / Could) that is deterministic and testable. Key design decisions:
  - Sources are embedded and tagged by **topic** (multi-label), not by persona, so new personas only need a new topic list.
  - All 11 interests from the task are in the topic taxonomy, and extra topics are allowed.
  - Briefings contain only the passages relevant to the persona, cited to a source.
  - Recency cutoff of 2025-04-06, one month before the newest source.
  - uv project with a `.venv`, delivered as a single private GitHub repository, with an agent-neutral skill in `skills/`.
- **Repository guidance:** wrote [CLAUDE.md](CLAUDE.md) for coding agents, covering the assignment, the data format, secrets handling and protected files.
- **File protection:** `.env`, `sources_06-05-25.json` and `task.md` can never be edited or deleted, and the protection files are covered too. It uses deny rules in [.claude/settings.json](.claude/settings.json) and a `PreToolUse` hook in [.claude/hooks/protect_files.py](.claude/hooks/protect_files.py). Both layers were verified: the hook script against 44 simulated tool calls (all passed, including fail-closed on bad input), and in a live session (file edits rejected by the deny rules, mutating shell commands blocked by the hook, read-only access still allowed). Shell matching is best-effort.
- **Requirement tracking:** every requirement in [REQUIREMENTS.md](REQUIREMENTS.md) now has a status marker (`[ ]` not started, `[~]` in progress, `[x]` complete and verified). Current tally: 0 of 46 complete (M: 0/20, S: 0/20, C: 0/6; M includes the sub-requirements M3.1 to M3.4).
- **Session rule:** [CLAUDE.md](CLAUDE.md) now requires each development session to keep the statuses current, check for regressions (tests, lint and type check once they exist) before finishing, and end with a summary of the requirements completed, unfinished, or regressed.
- **Documentation rule:** [CLAUDE.md](CLAUDE.md) now requires, after every prompt, a README update and code documented through Google-style docstrings and why-comments only. Ruff's `D` rules will enforce docstrings (S3), and a new requirement S20 covers the README architecture overview and the OpenAPI docs.
