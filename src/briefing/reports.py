"""Plain-text reports that show how the live pipeline behaves, to calibrate its settings."""

from collections.abc import Sequence
from datetime import date

from briefing.embeddings import Embedder
from briefing.models import Persona, Topic
from briefing.retrieval import (
    TaggedSource,
    choose_passages,
    gather_candidates,
    is_boilerplate,
    select_sources,
    split_passages,
)

# Passage thresholds shown in the per-topic sweep of `briefing passages`.
PASSAGE_SWEEP = (0.30, 0.35, 0.40, 0.45, 0.50)
# Unchosen passages listed per source beyond the chosen ones, so the cut-off can be judged.
EXTRA_PASSAGES_SHOWN = 2
SNIPPET_CHARS = 100


def passages_report(
    tagged: Sequence[TaggedSource],
    persona: Persona,
    persona_topics: Sequence[Topic],
    embedder: Embedder,
    *,
    top_k: int,
    per_topic_min: int,
    threshold: float,
    per_topic: int,
    per_source: int,
    per_source_per_topic: int | None = None,
    recent_window: tuple[date, date] | None = None,
    recency_bonus: float = 0.0,
) -> str:
    """Describe the sources and passages a persona's briefing would be built from.

    Shows, for each persona topic, how many passages clear each threshold and how many were
    chosen, then each selected source with its chosen passages (marked `*` with the topic
    they were chosen for, and `D` when the passage states a date inside `recent_window`), a
    few runners-up, and how many boilerplate passages were dropped. Embeds the passages
    through `embedder`.
    """
    selected = select_sources(tagged, persona.topic_ids, top_k, per_topic_min)
    topic_ids = [topic.id for topic in persona_topics]
    candidates = gather_candidates(selected, persona_topics, embedder, recent_window)
    chosen = choose_passages(
        candidates, topic_ids, threshold, per_topic, per_source, per_source_per_topic, recency_bonus
    )
    chosen_at = {(p.candidate.source_index, p.candidate.position): p for p in chosen}

    lines = [
        f"{persona.id} ({persona.position}, {persona.location})",
        f"{len(selected)} sources selected (top_k {top_k}, per-topic minimum {per_topic_min}); "
        f"passage threshold {threshold:.2f}, up to {per_topic} per topic and {per_source} per "
        "source"
        + (f" ({per_source_per_topic} per source per topic)" if per_source_per_topic else "")
        + (f"; recency bonus {recency_bonus:.2f}." if recency_bonus else "."),
        "",
        "Passages scoring at least each threshold, per topic (a passage can count for several):",
        "  " + f"{'topic':28}" + "".join(f"{value:>7.2f}" for value in PASSAGE_SWEEP) + "   chosen",
    ]
    for column, topic_id in enumerate(topic_ids):
        counts = "".join(
            f"{sum(1 for c in candidates if c.scores[column] >= value):7}"
            for value in PASSAGE_SWEEP
        )
        taken = sum(1 for p in chosen if p.topic_id == topic_id)
        lines.append(f"  {topic_id:28}{counts}   {taken:>6}")

    kept_sources = {p.candidate.source_index for p in chosen}
    dated = sum(1 for p in chosen if p.candidate.recent)
    lines += [
        "",
        f"{len(chosen)} passages chosen from {len(kept_sources)} of {len(selected)} selected "
        "sources; the rest have nothing above the threshold and would be dropped.",
        f"{dated} of the chosen passages state a date inside the recency window (D).",
        "",
        "Selected sources (* = passage chosen, with the topic it was chosen for; "
        "D = dated inside the window):",
    ]
    for source_index, source in enumerate(selected):
        texts = split_passages(source.prepared.clean_text)
        dropped = sum(1 for text in texts if is_boilerplate(text))
        own = [c for c in candidates if c.source_index == source_index]
        title = " ".join(source.prepared.source.title.split()) or "(no title)"
        tags = ", ".join(f"{tag.topic_id} {tag.score:.2f}" for tag in source.topics)
        lines += [
            f"[{source_index + 1}] {title[:80]}  [{source.prepared.source.url[:70]}]",
            f"    tags: {tags}",
            f"    {len(texts)} passages, {dropped} dropped as boilerplate, "
            f"{sum(1 for c in own if (c.source_index, c.position) in chosen_at)} chosen",
        ]
        own.sort(key=lambda c: (-max(c.scores), c.position))
        shown = [c for c in own if (c.source_index, c.position) in chosen_at]
        shown += [c for c in own if (c.source_index, c.position) not in chosen_at][
            :EXTRA_PASSAGES_SHOWN
        ]
        for candidate in sorted(shown, key=lambda c: (-max(c.scores), c.position)):
            pick = chosen_at.get((candidate.source_index, candidate.position))
            if pick:
                label, score = f"* {pick.topic_id}", pick.score
            else:
                best = candidate.scores.index(max(candidate.scores))
                label, score = f"  ({topic_ids[best]})", max(candidate.scores)
            snippet = " ".join(candidate.text.split())[:SNIPPET_CHARS]
            marker = "D" if candidate.recent else " "
            lines.append(f"     {score:.3f} {marker} {label:30} {snippet}")
        lines.append("")
    return "\n".join(lines).rstrip()
