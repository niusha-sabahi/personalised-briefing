"""Command-line entry point: serve the API, or audit dates, topics, tagging and passages."""

import argparse
import io
import sys
from collections import Counter
from collections.abc import Callable, Sequence
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
    source_embedding_text,
    topic_embedding_text,
)
from briefing.models import PreparedSource, Topic
from briefing.reports import passages_report
from briefing.retrieval import tag_corpus
from briefing.service import make_embedder
from briefing.sources import (
    MIN_CLEAN_CHARS,
    SourceDataError,
    is_recent,
    load_sources,
    prepare_sources,
    select_usable,
)
from briefing.tagging import similarity_matrix, tag_sources
from briefing.topics import Taxonomy, TaxonomyError, load_taxonomy

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
    return make_embedder(settings)


def _load_settings() -> Settings:
    """Read the settings, exiting with a short message that names what is missing or invalid."""
    try:
        return Settings()
    except ValidationError as exc:
        # Only field names are shown: an invalid value might be the secret itself.
        names = ", ".join(dict.fromkeys(str(error["loc"][0]).upper() for error in exc.errors()))
        print(f"Invalid settings ({names}). See .env.example.", file=sys.stderr)
        raise SystemExit(1) from exc


def _serve() -> None:
    """Start the API server after checking the settings and the topic and persona files."""
    settings = _load_settings()
    try:
        load_taxonomy(settings.topics_path, settings.personas_path)
    except TaxonomyError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc
    # A factory, so the app is built (and the sources loaded) once in the server process.
    uvicorn.run("briefing.api:create_app", factory=True, host="127.0.0.1", port=8000)


def _run_live(
    build: Callable[[Settings, Taxonomy, list[PreparedSource], CachedEmbedder], str],
) -> None:
    """Run a report that calls OpenAI, turning setup and API failures into a short message."""
    settings = _load_settings()
    try:
        taxonomy = load_taxonomy(settings.topics_path, settings.personas_path)
        prepared = prepare_sources(load_sources(settings.sources_path), settings.latest_date)
        usable = select_usable(prepared, settings.cutoff_date)
        embedder = _build_embedder(settings)
        report = build(settings, taxonomy, usable, embedder)
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


def _run_tags(threshold: float | None) -> None:
    """Run `briefing tags`."""

    def build(
        settings: Settings,
        taxonomy: Taxonomy,
        usable: list[PreparedSource],
        embedder: CachedEmbedder,
    ) -> str:
        value = settings.tagging_threshold if threshold is None else threshold
        return tags_report(usable, taxonomy.topics, embedder, value, settings.max_tags_per_source)

    _run_live(build)


def _run_passages(
    persona_id: str | None, threshold: float | None, recency_bonus: float | None
) -> None:
    """Run `briefing passages` for one persona, or for all of them."""

    def build(
        settings: Settings,
        taxonomy: Taxonomy,
        usable: list[PreparedSource],
        embedder: CachedEmbedder,
    ) -> str:
        if persona_id is None:
            personas = list(taxonomy.personas)
        else:
            persona = taxonomy.persona(persona_id)
            if persona is None:
                known = ", ".join(p.id for p in taxonomy.personas)
                raise TaxonomyError(f"Unknown persona {persona_id!r}. Known personas: {known}.")
            personas = [persona]
        tagged = tag_corpus(
            usable,
            taxonomy.topics,
            embedder,
            settings.tagging_threshold,
            settings.max_tags_per_source,
        )
        value = settings.passage_threshold if threshold is None else threshold
        bonus = settings.recency_bonus if recency_bonus is None else recency_bonus
        blocks = []
        for persona in personas:
            topics = [t for t in taxonomy.topics if t.id in persona.topic_ids]
            topics.sort(key=lambda t: persona.topic_ids.index(t.id))
            blocks.append(
                passages_report(
                    tagged,
                    persona,
                    topics,
                    embedder,
                    top_k=settings.top_k,
                    per_topic_min=settings.per_topic_min,
                    threshold=value,
                    per_topic=settings.max_passages_per_topic,
                    per_source=settings.max_passages_per_source,
                    per_source_per_topic=settings.max_passages_per_source_per_topic,
                    recent_window=(settings.cutoff_date, settings.latest_date),
                    recency_bonus=bonus,
                )
            )
        return ("\n\n" + "=" * 100 + "\n\n").join(blocks)

    _run_live(build)


def run(argv: Sequence[str] | None = None) -> None:
    """Run the `briefing` command: `serve` (the default), `dates`, `topics`, `tags`, `passages`."""
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
    passages = commands.add_parser(
        "passages",
        help="show the sources and passages each persona's briefing would use; needs the API key",
    )
    passages.add_argument("--persona", help="persona id (default: every persona)")
    passages.add_argument("--threshold", type=float, help="override PASSAGE_THRESHOLD for this run")
    passages.add_argument(
        "--recency-bonus",
        type=float,
        help="override RECENCY_BONUS for this run (0 shows the selection without it)",
    )
    args = parser.parse_args(argv)

    if args.command in ("tags", "passages"):
        # Titles and passages can hold characters a Windows console cannot print.
        if isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if args.command == "tags":
            _run_tags(args.threshold)
        else:
            _run_passages(args.persona, args.threshold, args.recency_bonus)
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
    _serve()
