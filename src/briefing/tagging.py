"""Multi-label topic tagging of sources by cosine similarity."""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

Scores = NDArray[np.float64]


@dataclass(frozen=True)
class Tag:
    """A topic a source was tagged with, and the cosine similarity that earned it."""

    topic_id: str
    score: float


def similarity_matrix(
    source_vectors: Sequence[Sequence[float]], topic_vectors: Sequence[Sequence[float]]
) -> Scores:
    """Return cosine similarities, one row per source and one column per topic."""
    sources = np.asarray(source_vectors, dtype=np.float64)
    topics = np.asarray(topic_vectors, dtype=np.float64)
    sources = sources / np.linalg.norm(sources, axis=1, keepdims=True)
    topics = topics / np.linalg.norm(topics, axis=1, keepdims=True)
    result: Scores = sources @ topics.T
    return result


def tag_sources(
    scores: Scores, topic_ids: Sequence[str], threshold: float, max_tags: int
) -> list[list[Tag]]:
    """Tag each source with every topic scoring at or above `threshold` (M3.3).

    Args:
        scores: Similarity matrix from `similarity_matrix` (sources by topics).
        topic_ids: Topic id for each column of `scores`.
        threshold: Minimum similarity for a tag; a score equal to it qualifies.
        max_tags: Most tags one source may keep, strongest first.

    Returns:
        One list of tags per source, best score first. The list is empty when no
        topic qualifies, and such a source is never used in a briefing.
    """
    tagged: list[list[Tag]] = []
    for row in scores:
        tags = [
            Tag(topic_id, float(score))
            for topic_id, score in zip(topic_ids, row, strict=True)
            if score >= threshold
        ]
        # Topic id breaks ties so the result never depends on column order.
        tags.sort(key=lambda tag: (-tag.score, tag.topic_id))
        tagged.append(tags[:max_tags])
    return tagged
