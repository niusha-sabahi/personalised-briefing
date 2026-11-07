"""Command-line entry point: serve the API, or audit dates, topics and tagging."""

import argparse
import io
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import numpy as np
import openai
import uvicorn
from pydantic import ValidationError

from briefing.config import (
    DEFAULT_CUTOFF_DATE,
    DEFAULT_LATEST_DATE,
    DEFAULT_PERSONAS_PATH,
    DEFAULT_SOURCES_PATH,
    DEFAULT_TOPICS_PATH,
    Settings,
)
from briefing.embeddings import (
    CachedEmbedder,
    Embedder,
    EmbeddingCache,
    OpenAIEmbedder,
    source_embedding_text,
    topic_embedding_text,
)
from briefing.models import PreparedSource, Topic
from briefing.sources import (
    MIN_CLEAN_CHARS,
    SourceDataError,
    is_recent,
    load_sources,
    prepare_sources,
    select_usable,
)
from briefing.tagging import similarity_matrix, tag_sources
from briefing.topics import TaxonomyError, load_taxonomy

# Thresholds shown in the calibration table of `briefing tags`.
SWEEP_THRESHOLDS = (0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50)
# How many top-scoring sources per topic `briefing tags` lists for a manual relevance check.
TOP_PER_TOPIC = 5


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


def topics_report(topics_path: Path, personas_path: Path) -> str:
    """Validate topics.yaml and personas.yaml and describe what they define."""
    taxonomy = load_taxonomy(topics_path, personas_path)
    lines = [
        f"{len(taxonomy.topics)} topics, {len(taxonomy.personas)} personas: files are valid.",
        "",
    ]
    for persona in taxonomy.personas:
        lines.append(f"{persona.id} ({persona.position}, {persona.location})")
        lines.extend(f"  - {topic_id}" for topic_id in persona.topic_ids)
    unused = [
        t.id for t in taxonomy.topics if not any(t.id in p.topic_ids for p in taxonomy.personas)
    ]
    if unused:
        lines.extend(["", "Topics no persona uses: " + ", ".join(unused)])
    return "\n".join(lines)


def tags_report(
    items: Sequence[PreparedSource],
    topics: Sequence[Topic],
    embedder: Embedder,
    threshold: float,
    max_tags: int,
) -> str:
    """Embed the sources and topics and describe the score distribution to calibrate a threshold.

    Shows each topic's score quantiles, how many sources are tagged at a range of
    thresholds, and the best-scoring sources per topic so relevance can be judged by eye.
    """
    source_vectors = embedder.embed([source_embedding_text(item) for item in items])
    topic_vectors = embedder.embed([topic_embedding_text(topic) for topic in topics])
    scores = similarity_matrix(source_vectors, topic_vectors)
    topic_ids = [topic.id for topic in topics]

    lines = [f"{len(items)} sources, {len(topics)} topics.", "", "Score quantiles per topic:"]
    lines.append(f"  {'topic':28} {'min':>6} {'median':>6} {'p90':>6} {'max':>6}")
    for column, topic_id in enumerate(topic_ids):
        low, mid, high, top = np.percentile(scores[:, column], [0, 50, 90, 100])
        lines.append(f"  {topic_id:28} {low:6.3f} {mid:6.3f} {high:6.3f} {top:6.3f}")

    lines += ["", "Sources tagged at each threshold (uncapped, any topic):"]
    for value in SWEEP_THRESHOLDS:
        tagged = int((scores >= value).any(axis=1).sum())
        average = float((scores >= value).sum(axis=1).mean())
        lines.append(
            f"  >= {value:.2f}: {tagged:3} tagged, {len(items) - tagged:3} untagged, "
            f"{average:.2f} tags per source"
        )

    tags = tag_sources(scores, topic_ids, threshold, max_tags)
    tagged_now = sum(1 for source_tags in tags if source_tags)
    lines += [
        "",
        f"At threshold {threshold:.2f}, max {max_tags} tags: {tagged_now} tagged, "
        f"{len(items) - tagged_now} untagged.",
        "",
        f"Top {TOP_PER_TOPIC} sources per topic (* = tagged with that topic):",
    ]
    for column, topic_id in enumerate(topic_ids):
        lines.append(f"  {topic_id}")
        order = sorted(
            range(len(items)), key=lambda row: (-scores[row, column], items[row].source.url)
        )
        for row in order[:TOP_PER_TOPIC]:
            mark = "*" if any(tag.topic_id == topic_id for tag in tags[row]) else " "
            title = items[row].source.title[:70]
            lines.append(
                f"   {mark} {scores[row, column]:.3f}  {title}  [{items[row].source.url[:60]}]"
            )
    return "\n".join(lines)


def _build_embedder(settings: Settings) -> CachedEmbedder:
    """Create the cached OpenAI embedder described by `settings`."""
    client = openai.OpenAI(api_key=settings.openai_api_key.get_secret_value(), timeout=60.0)
    cache = EmbeddingCache(settings.cache_path, settings.embedding_model)
    return CachedEmbedder(OpenAIEmbedder(client, settings.embedding_model), cache)


def _run_tags(threshold: float | None) -> None:
    """Run `briefing tags`, turning setup and API failures into a short message."""
    try:
        settings = Settings()
    except ValidationError as exc:
        missing = ", ".join(str(error["loc"][0]).upper() for error in exc.errors())
        print(f"Invalid settings ({missing}). See .env.example.", file=sys.stderr)
        raise SystemExit(1) from exc
    try:
        taxonomy = load_taxonomy(settings.topics_path, settings.personas_path)
        prepared = prepare_sources(load_sources(settings.sources_path), settings.latest_date)
        usable = select_usable(prepared, settings.cutoff_date)
        embedder = _build_embedder(settings)
        value = settings.tagging_threshold if threshold is None else threshold
        report = tags_report(usable, taxonomy.topics, embedder, value, settings.max_tags_per_source)
    except (TaxonomyError, SourceDataError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc
    except openai.OpenAIError as exc:
        # Only the error class and status are shown: provider messages can echo key fragments.
        status = getattr(exc, "status_code", None)
        print(
            f"OpenAI request failed: {type(exc).__name__} {status or ''}".strip(), file=sys.stderr
        )
        raise SystemExit(1) from exc
    print(report)
    print(f"\nEmbeddings: {embedder.misses} requested from OpenAI, {embedder.hits} from cache.")


def run(argv: Sequence[str] | None = None) -> None:
    """Run the `briefing` command: `serve` (the default), `dates`, `topics` or `tags`."""
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
    topics = commands.add_parser("topics", help="validate topics.yaml and personas.yaml")
    topics.add_argument("--topics", type=Path, default=DEFAULT_TOPICS_PATH)
    topics.add_argument("--personas", type=Path, default=DEFAULT_PERSONAS_PATH)
    tags = commands.add_parser(
        "tags",
        help="embed sources and topics (cached) and report tagging scores; needs the API key",
    )
    tags.add_argument("--threshold", type=float, help="override TAGGING_THRESHOLD for this run")
    args = parser.parse_args(argv)

    if args.command == "tags":
        if isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        _run_tags(args.threshold)
        return
    if args.command == "topics":
        try:
            print(topics_report(args.topics, args.personas))
        except TaxonomyError as exc:
            print(exc, file=sys.stderr)
            raise SystemExit(1) from exc
        return
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
