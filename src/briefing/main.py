"""Command-line entry point: start the API server or audit publication dates."""

import argparse
import io
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import uvicorn

from briefing.config import DEFAULT_CUTOFF_DATE, DEFAULT_LATEST_DATE, DEFAULT_SOURCES_PATH
from briefing.sources import (
    MIN_CLEAN_CHARS,
    SourceDataError,
    is_recent,
    load_sources,
    prepare_sources,
)


def dates_report(sources_path: Path, cutoff: date, latest: date, only: str | None) -> str:
    """Build a text table of every source's derived date, rule and keep/exclude decision."""
    prepared = prepare_sources(load_sources(sources_path), latest)
    rows: list[str] = []
    rules: Counter[str] = Counter()
    kept = 0
    for item in prepared:
        published = item.published
        long_enough = len(item.clean_text) >= MIN_CLEAN_CHARS
        keep = is_recent(published, cutoff) and long_enough
        kept += keep
        rule = published.rule if published else "none"
        rules[rule] += 1
        if (only == "kept" and not keep) or (only == "excluded" and keep):
            continue
        shown = published.value.isoformat() if published else "-"
        if published and published.precision == "month":
            shown = shown[:7]
        reason = "" if keep else (" (short)" if published and not long_enough else "")
        rows.append(
            f"{'KEEP' if keep else 'DROP':4}  {shown:10}  {rule:18} {item.source.url[:90]}{reason}"
        )
    summary = [
        f"{len(prepared)} sources, {kept} kept (published on or after {cutoff}), "
        f"{len(prepared) - kept} excluded.",
        "Rules used: " + ", ".join(f"{name}={count}" for name, count in sorted(rules.items())),
    ]
    return "\n".join([*rows, "", *summary])


def run(argv: Sequence[str] | None = None) -> None:
    """Run the `briefing` command: `serve` (the default) or `dates`."""
    parser = argparse.ArgumentParser(
        prog="briefing", description="Personalised briefing generator."
    )
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("serve", help="start the API server on http://127.0.0.1:8000 (default)")
    dates = commands.add_parser("dates", help="audit the publication date found for each source")
    dates.add_argument("--sources", type=Path, default=DEFAULT_SOURCES_PATH)
    dates.add_argument("--cutoff", type=date.fromisoformat, default=DEFAULT_CUTOFF_DATE)
    dates.add_argument("--latest", type=date.fromisoformat, default=DEFAULT_LATEST_DATE)
    dates.add_argument("--only", choices=["kept", "excluded"], help="show only these rows")
    args = parser.parse_args(argv)

    if args.command == "dates":
        # Page titles and URLs can hold characters a Windows console cannot print.
        if isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        try:
            print(dates_report(args.sources, args.cutoff, args.latest, args.only))
        except SourceDataError as exc:
            print(exc, file=sys.stderr)
            raise SystemExit(1) from exc
        return
    uvicorn.run("briefing.api:app", host="127.0.0.1", port=8000)
