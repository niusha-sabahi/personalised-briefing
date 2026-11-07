"""Persona retrieval: choose tagged sources for a persona, then the passages worth sending.

The selection logic is pure. The functions that take an `Embedder` only use its interface,
so tests pass a fake and nothing here talks to OpenAI.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from briefing.embeddings import Embedder, source_embedding_text, topic_embedding_text
from briefing.models import Passage, PreparedSource, Topic
from briefing.tagging import Tag, similarity_matrix, tag_sources

# Paragraphs shorter than this are merged into a neighbour: a heading or a one-line caption
# has too little text to match a topic on its own.
MIN_PASSAGE_CHARS = 200
# Longer paragraphs are split at sentence ends so a passage stays about one idea.
MAX_PASSAGE_CHARS = 1200

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class TaggedSource:
    """A usable source with the topic tags it earned (possibly none)."""

    prepared: PreparedSource
    tags: tuple[Tag, ...]


@dataclass(frozen=True)
class SelectedSource:
    """A source chosen for a persona, with only the persona's topics it carries (best first)."""

    prepared: PreparedSource
    topics: tuple[Tag, ...]

    @property
    def best_score(self) -> float:
        """The source's highest score among the persona's topics."""
        return self.topics[0].score


@dataclass(frozen=True)
class BriefingContext:
    """Everything the generator may use: the sources kept and their relevant passages."""

    sources: tuple[SelectedSource, ...]
    passages: tuple[Passage, ...]


# --- Tagging a corpus -----------------------------------------------------------------


def tag_corpus(
    items: Sequence[PreparedSource],
    topics: Sequence[Topic],
    embedder: Embedder,
    threshold: float,
    max_tags: int,
) -> list[TaggedSource]:
    """Embed the sources and topics (cached by the embedder) and tag every source (M3.3)."""
    source_vectors = embedder.embed([source_embedding_text(item) for item in items])
    topic_vectors = embedder.embed([topic_embedding_text(topic) for topic in topics])
    scores = similarity_matrix(source_vectors, topic_vectors)
    tags = tag_sources(scores, [topic.id for topic in topics], threshold, max_tags)
    return [TaggedSource(item, tuple(t)) for item, t in zip(items, tags, strict=True)]


# --- Choosing sources for a persona (M3.4) ----------------------------------------------


def _score_for(source: SelectedSource, topic_id: str) -> float | None:
    return next((tag.score for tag in source.topics if tag.topic_id == topic_id), None)


def select_sources(
    tagged: Sequence[TaggedSource],
    persona_topic_ids: Sequence[str],
    top_k: int,
    per_topic_min: int,
) -> list[SelectedSource]:
    """Pick up to `top_k` sources for a persona, so no single topic crowds out the others.

    Candidates carry at least one of the persona's topics. They are ranked by their best
    score among those topics, ties broken by URL. Each persona topic first gets up to
    `per_topic_min` of the best sources carrying it (a source already chosen for another
    topic counts toward every topic it carries); the remaining places go to the best
    candidates overall. If the minimums alone exceed `top_k`, topics earlier in the
    persona's list win.

    Returns:
        The chosen sources in overall rank order.
    """
    persona = set(persona_topic_ids)
    candidates: list[SelectedSource] = []
    for item in tagged:
        # Tags are already strongest first, so the filtered tuple keeps that order.
        mine = tuple(tag for tag in item.tags if tag.topic_id in persona)
        if mine:
            candidates.append(SelectedSource(item.prepared, mine))
    candidates.sort(key=lambda c: (-c.best_score, c.prepared.source.url))

    chosen: dict[str, SelectedSource] = {}
    for topic_id in persona_topic_ids:
        carrying = [c for c in candidates if _score_for(c, topic_id) is not None]
        carrying.sort(key=lambda c: (-(_score_for(c, topic_id) or 0.0), c.prepared.source.url))
        have = sum(1 for c in carrying if c.prepared.source.url in chosen)
        for candidate in carrying:
            if have >= per_topic_min or len(chosen) >= top_k:
                break
            if candidate.prepared.source.url not in chosen:
                chosen[candidate.prepared.source.url] = candidate
                have += 1
    for candidate in candidates:
        if len(chosen) >= top_k:
            break
        chosen.setdefault(candidate.prepared.source.url, candidate)
    return [c for c in candidates if c.prepared.source.url in chosen]


# --- Passages (M8) ---------------------------------------------------------------------


def _pack(sentences: list[str]) -> list[str]:
    """Join sentences into chunks of at most MAX_PASSAGE_CHARS, cutting oversized ones."""
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > MAX_PASSAGE_CHARS:
            # No sentence end to cut at (a table or a run of links): cut at a word break.
            cut = sentence.rfind(" ", 0, MAX_PASSAGE_CHARS)
            cut = cut if cut > 0 else MAX_PASSAGE_CHARS
            if current:
                chunks.append(current)
                current = ""
            chunks.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + 1 + len(sentence) > MAX_PASSAGE_CHARS:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks


def split_passages(clean_text: str) -> list[str]:
    """Split cleaned text into paragraph-sized passages of roughly 200 to 1200 characters.

    Paragraphs are the unit. Long ones are split at sentence ends, and short ones (headings,
    captions) are merged with the next so each passage has enough text to be matched.
    """
    pieces: list[str] = []
    for paragraph in (p.strip() for p in clean_text.split("\n\n")):
        if not paragraph:
            continue
        if len(paragraph) <= MAX_PASSAGE_CHARS:
            pieces.append(paragraph)
        else:
            pieces.extend(_pack(_SENTENCE_END.split(paragraph)))

    passages: list[str] = []
    pending = ""
    for piece in pieces:
        if pending and len(pending) + 2 + len(piece) > MAX_PASSAGE_CHARS:
            passages.append(pending)
            pending = ""
        pending = f"{pending}\n\n{piece}" if pending else piece
        if len(pending) >= MIN_PASSAGE_CHARS:
            passages.append(pending)
            pending = ""
    if pending:
        # A short tail joins the previous passage when it fits, otherwise it stands alone.
        if passages and len(passages[-1]) + 2 + len(pending) <= MAX_PASSAGE_CHARS:
            passages[-1] = f"{passages[-1]}\n\n{pending}"
        else:
            passages.append(pending)
    return passages


@dataclass(frozen=True)
class PassageMatch:
    """A passage kept for the briefing: its position in the source, best topic and score."""

    index: int
    topic_id: str
    score: float


def rank_passages(
    passage_vectors: Sequence[Sequence[float]],
    topic_ids: Sequence[str],
    topic_vectors: Sequence[Sequence[float]],
    threshold: float,
    max_passages: int,
) -> list[PassageMatch]:
    """Keep the passages that match a persona topic well enough, best `max_passages` of them.

    Each passage is matched to its best-scoring topic (ties go to the earlier topic). Passages
    below `threshold` are dropped, so off-topic text never reaches the model.

    Returns:
        The kept passages in document order, which reads best in a briefing.
    """
    if not passage_vectors:
        return []
    scores = similarity_matrix(passage_vectors, topic_vectors)
    matches = [
        PassageMatch(index, topic_ids[int(row.argmax())], float(row.max()))
        for index, row in enumerate(scores)
        if row.max() >= threshold
    ]
    matches.sort(key=lambda m: (-m.score, m.index))
    return sorted(matches[:max_passages], key=lambda m: m.index)


def build_context(
    selected: Sequence[SelectedSource],
    persona_topics: Sequence[Topic],
    embedder: Embedder,
    threshold: float,
    max_passages: int,
) -> BriefingContext:
    """Choose the relevant passages of each selected source (M8).

    Passages are embedded with the same cached embedder as everything else. A source with
    no passage above the threshold is dropped: it has nothing relevant to cite. Passage ids
    look like `s2p3` (second kept source, third kept passage) and are what the model cites.
    """
    topic_ids = [topic.id for topic in persona_topics]
    topic_vectors = embedder.embed([topic_embedding_text(topic) for topic in persona_topics])

    kept: list[tuple[SelectedSource, list[tuple[str, PassageMatch]]]] = []
    for source in selected:
        texts = split_passages(source.prepared.clean_text)
        vectors = embedder.embed(texts) if texts else []
        matches = rank_passages(vectors, topic_ids, topic_vectors, threshold, max_passages)
        if matches:
            kept.append((source, [(texts[m.index], m) for m in matches]))

    passages: list[Passage] = []
    for source_number, (source, pairs) in enumerate(kept, start=1):
        for passage_number, (text, match) in enumerate(pairs, start=1):
            passages.append(
                Passage(
                    id=f"s{source_number}p{passage_number}",
                    source_url=source.prepared.source.url,
                    text=text,
                    topic_id=match.topic_id,
                    score=match.score,
                )
            )
    return BriefingContext(tuple(source for source, _ in kept), tuple(passages))
