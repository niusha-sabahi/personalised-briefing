"""Persona retrieval: choose tagged sources for a persona, then the passages worth sending.

The selection logic is pure. The functions that take an `Embedder` only use its interface,
so tests pass a fake and nothing here talks to OpenAI.
"""

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from briefing.embeddings import Embedder, source_embedding_text, topic_embedding_text
from briefing.models import Passage, PreparedSource, Topic
from briefing.sources import dates_in_text
from briefing.tagging import Tag, similarity_matrix, tag_sources

# Paragraphs shorter than this are merged into a neighbour: a heading or a one-line caption
# has too little text to match a topic on its own.
MIN_PASSAGE_CHARS = 200
# Longer paragraphs are split at sentence ends so a passage stays about one idea.
MAX_PASSAGE_CHARS = 1200
# A passage made mostly of URLs is a list of links, not prose.
URL_SHARE_LIMIT = 0.15

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_URL = re.compile(r"https?://\S+")
# What is left of a Markdown link after cleaning when its text and address were separated.
_LINK_REMNANT = re.compile(r"\]\(https?://")
# Consent banners, legal footers and page furniture. Deliberately no generic words such as
# "copyright", which also appear in real news about copyright cases.
_PAGE_FURNITURE = re.compile(
    r"service marks?|not responsible for the content|do(?:es)? not constitute or imply "
    r"endorsement|provided as a service|all rights reserved|privacy (?:policy|overview)|"
    r"terms (?:of use|of service|and conditions)|cookies?\b|technical storage or access|"
    r"accept all|subscribe (?:to|now|today)|sign up (?:for|to|now)|newsletter|"
    r"downloads? (?:article|pdf|the)|read more|share (?:this|on)|follow us|"
    r"related (?:articles|posts|content)|(?:recent|recommended) articles|click here",
    re.IGNORECASE,
)
_NUMBERED_START = re.compile(r"^\s*\d{1,3}[^\w\s]{1,2}\s")
_CITATION_MARKER = re.compile(
    r"\bet al\b|\bdoi\b|\baccessed\b|\bavailable at\b|\bMMWR Morb\b|\bAtlanta, GA\b",
    re.IGNORECASE,
)


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

    @property
    def primary_topic(self) -> str:
        """The persona topic the source matches best."""
        return self.topics[0].topic_id


@dataclass(frozen=True)
class PassageCandidate:
    """A passage of a selected source, scored against every persona topic.

    `recent` means the passage itself carries a date inside the recency window, which marks
    it as news about the period and not an evergreen explainer.
    """

    source_index: int
    position: int
    text: str
    scores: tuple[float, ...]
    recent: bool = False


@dataclass(frozen=True)
class ChosenPassage:
    """A passage chosen for a persona topic, and the score that earned it."""

    candidate: PassageCandidate
    topic_id: str
    score: float


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
    `per_topic_min` sources, in rounds: every topic gets its first before any gets its
    second, so a long list of topics cannot starve the last ones. A chosen source counts
    only for the topic it matches best, so a source that merely mentions a topic cannot
    stand in for it. Topics short of sources take the best-scoring carriers of that topic.
    The remaining places go to the best candidates overall. If the minimums exceed `top_k`,
    topics earlier in the persona's list win the later rounds.

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
    # Sources taken specifically to fill a topic, which count for it even when another topic
    # is their best match.
    taken_for: dict[str, set[str]] = {topic_id: set() for topic_id in persona_topic_ids}
    for round_number in range(1, per_topic_min + 1):
        for topic_id in persona_topic_ids:
            primary = {url for url, c in chosen.items() if c.primary_topic == topic_id}
            if len(primary | taken_for[topic_id]) >= round_number or len(chosen) >= top_k:
                continue
            carrying = [c for c in candidates if _score_for(c, topic_id) is not None]
            carrying.sort(key=lambda c: (-(_score_for(c, topic_id) or 0.0), c.prepared.source.url))
            best = next((c for c in carrying if c.prepared.source.url not in chosen), None)
            if best is not None:
                chosen[best.prepared.source.url] = best
                taken_for[topic_id].add(best.prepared.source.url)
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


def is_boilerplate(passage: str) -> bool:
    """Return True for passages that are not article content (M8).

    Catches lists of links (mostly URLs, or leftover link syntax), consent banners and legal
    footers, and numbered reference-list entries. These match topic descriptions well
    because they repeat names such as "CDC" or "MMWR", so they must go before ranking.
    The rules are heuristics: they leave some page furniture in and the model is also told
    to ignore it.
    """
    url_characters = sum(len(url) for url in _URL.findall(passage))
    if url_characters / max(len(passage), 1) > URL_SHARE_LIMIT:
        return True
    if len(_LINK_REMNANT.findall(passage)) >= 2:
        return True
    furniture = len(_PAGE_FURNITURE.findall(passage))
    if furniture >= 2 or (furniture >= 1 and len(passage) < 300):
        return True
    return bool(_NUMBERED_START.match(passage) and _CITATION_MARKER.search(passage))


def gather_candidates(
    selected: Sequence[SelectedSource],
    persona_topics: Sequence[Topic],
    embedder: Embedder,
    recent_window: tuple[date, date] | None = None,
) -> list[PassageCandidate]:
    """Split the selected sources into passages and score each against every persona topic.

    Boilerplate passages are dropped before embedding, so they cost nothing and cannot be
    chosen. Scores are in the order of `persona_topics`. With a `recent_window` (earliest,
    latest), a passage that itself states a date inside it is marked `recent`.
    """
    topic_vectors = embedder.embed([topic_embedding_text(topic) for topic in persona_topics])
    candidates: list[PassageCandidate] = []
    for source_index, source in enumerate(selected):
        texts = [t for t in split_passages(source.prepared.clean_text) if not is_boilerplate(t)]
        if not texts:
            continue
        scores = similarity_matrix(embedder.embed(texts), topic_vectors)
        for position, (text, row) in enumerate(zip(texts, scores, strict=True)):
            recent = recent_window is not None and any(
                recent_window[0] <= when <= recent_window[1]
                for when in dates_in_text(text, recent_window[1])
            )
            candidates.append(
                PassageCandidate(source_index, position, text, tuple(float(x) for x in row), recent)
            )
    return candidates


def _best_for_topic(
    candidates: Sequence[PassageCandidate], column: int, threshold: float, recency_bonus: float
) -> list[PassageCandidate]:
    """Candidates scoring at least `threshold` for a topic, best first, ties in document order.

    The bonus only reorders: a passage must reach the threshold on its own score first.
    """
    qualifying = [c for c in candidates if c.scores[column] >= threshold]
    return sorted(
        qualifying,
        key=lambda c: (
            -(c.scores[column] + (recency_bonus if c.recent else 0.0)),
            c.source_index,
            c.position,
        ),
    )


def choose_passages(
    candidates: Sequence[PassageCandidate],
    topic_ids: Sequence[str],
    threshold: float,
    per_topic: int,
    per_source: int,
    per_source_per_topic: int | None = None,
    recency_bonus: float = 0.0,
) -> list[ChosenPassage]:
    """Choose each topic's best passages, so every persona topic can have a section (M8).

    A passage qualifies for a topic when it scores at least `threshold` for it. Topics take
    turns picking their best remaining passage (earlier topics first within a round), until
    each has `per_topic` or runs out, so a topic with a dominant neighbour is not crowded
    out. A passage serves one topic, and no source supplies more than `per_source`, nor
    more than `per_source_per_topic` to any one topic (unset means no such limit), so a
    topic draws on several sources and not just the one with the most on-topic text. A
    passage about funding inside an AI article therefore appears under funding even though
    AI is its best match overall. Passages marked `recent` rank `recency_bonus` higher when a
    topic picks (qualifying and the reported score are unchanged), so news dated inside the
    window beats an evergreen explainer of similar relevance.

    Returns:
        The chosen passages in document order (by source, then position).
    """
    ranked = [
        _best_for_topic(candidates, column, threshold, recency_bonus)
        for column in range(len(topic_ids))
    ]
    cursor = [0] * len(topic_ids)
    picked = [0] * len(topic_ids)
    taken: set[tuple[int, int]] = set()
    from_source: Counter[int] = Counter()
    from_source_for_topic: Counter[tuple[int, int]] = Counter()
    chosen: list[ChosenPassage] = []
    progress = True
    while progress:
        progress = False
        for column, topic_id in enumerate(topic_ids):
            if picked[column] >= per_topic:
                continue
            while cursor[column] < len(ranked[column]):
                candidate = ranked[column][cursor[column]]
                cursor[column] += 1
                key = (candidate.source_index, candidate.position)
                if key in taken or from_source[candidate.source_index] >= per_source:
                    continue
                topic_key = (candidate.source_index, column)
                if (
                    per_source_per_topic is not None
                    and from_source_for_topic[topic_key] >= per_source_per_topic
                ):
                    continue
                taken.add(key)
                from_source[candidate.source_index] += 1
                from_source_for_topic[topic_key] += 1
                picked[column] += 1
                chosen.append(ChosenPassage(candidate, topic_id, candidate.scores[column]))
                progress = True
                break
    return sorted(chosen, key=lambda p: (p.candidate.source_index, p.candidate.position))


def build_context(
    selected: Sequence[SelectedSource],
    persona_topics: Sequence[Topic],
    embedder: Embedder,
    threshold: float,
    per_topic: int,
    per_source: int,
    per_source_per_topic: int | None = None,
    recent_window: tuple[date, date] | None = None,
    recency_bonus: float = 0.0,
) -> BriefingContext:
    """Choose the passages each persona topic will be written from (M8).

    Passages are embedded with the same cached embedder as everything else. A source with
    no chosen passage is dropped: it has nothing relevant to cite. Passage ids look like
    `s2p3` (second kept source, third kept passage) and are what the model cites.
    """
    candidates = gather_candidates(selected, persona_topics, embedder, recent_window)
    chosen = choose_passages(
        candidates,
        [topic.id for topic in persona_topics],
        threshold,
        per_topic,
        per_source,
        per_source_per_topic,
        recency_bonus,
    )
    kept = sorted({p.candidate.source_index for p in chosen})
    source_number = {index: number for number, index in enumerate(kept, start=1)}
    in_source: Counter[int] = Counter()
    passages: list[Passage] = []
    for item in chosen:
        index = item.candidate.source_index
        in_source[index] += 1
        passages.append(
            Passage(
                id=f"s{source_number[index]}p{in_source[index]}",
                source_url=selected[index].prepared.source.url,
                text=item.candidate.text,
                topic_id=item.topic_id,
                score=item.score,
            )
        )
    return BriefingContext(tuple(selected[i] for i in kept), tuple(passages))
