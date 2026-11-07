from collections.abc import Sequence

import numpy as np
import pytest

from briefing.main import tags_report
from briefing.models import PreparedSource, Source, Topic
from briefing.tagging import Tag, similarity_matrix, tag_sources

TOPIC_IDS = ["a", "b", "c"]


def scores_of(*rows: Sequence[float]) -> np.ndarray:
    return np.array(rows, dtype=np.float64)


# --- similarity ----------------------------------------------------------------------


def test_cosine_of_identical_orthogonal_and_opposite_vectors() -> None:
    result = similarity_matrix([[1, 0], [0, 2]], [[3, 0], [0, -1]])
    assert result.round(6).tolist() == [[1.0, 0.0], [0.0, -1.0]]


def test_cosine_ignores_vector_length() -> None:
    small = similarity_matrix([[1, 1]], [[1, 0]])
    large = similarity_matrix([[100, 100]], [[7, 0]])
    assert small[0, 0] == pytest.approx(large[0, 0])


# --- tagging -------------------------------------------------------------------------


def test_source_gets_every_topic_at_or_above_threshold() -> None:
    tags = tag_sources(scores_of([0.6, 0.5, 0.1]), TOPIC_IDS, 0.4, max_tags=3)
    assert tags == [[Tag("a", 0.6), Tag("b", 0.5)]]


def test_score_equal_to_threshold_is_tagged_and_just_below_is_not() -> None:
    tags = tag_sources(scores_of([0.35, 0.3499999]), ["a", "b"], 0.35, max_tags=3)
    assert [t.topic_id for t in tags[0]] == ["a"]


def test_source_with_no_qualifying_topic_has_no_tags() -> None:
    assert tag_sources(scores_of([0.1, 0.2, 0.3]), TOPIC_IDS, 0.5, max_tags=3) == [[]]


def test_tags_are_capped_keeping_the_strongest() -> None:
    tags = tag_sources(scores_of([0.5, 0.9, 0.7]), TOPIC_IDS, 0.1, max_tags=2)
    assert [t.topic_id for t in tags[0]] == ["b", "c"]


def test_equal_scores_are_ordered_by_topic_id() -> None:
    tags = tag_sources(scores_of([0.5, 0.5, 0.5]), ["z", "m", "a"], 0.1, max_tags=2)
    assert [t.topic_id for t in tags[0]] == ["a", "m"]


def test_each_source_is_tagged_independently() -> None:
    tags = tag_sources(
        scores_of([0.9, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.8, 0.8]), TOPIC_IDS, 0.5, 3
    )
    assert [[t.topic_id for t in row] for row in tags] == [["a"], [], ["b", "c"]]


# --- calibration report --------------------------------------------------------------


class KeywordEmbedder:
    """Maps text to a 2-d vector: how much it mentions 'health' and how much 'startup'."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[t.lower().count("health") + 0.1, t.lower().count("startup") + 0.1] for t in texts]


def item(url: str, title: str, text: str) -> PreparedSource:
    source = Source(id=url, url=url, title=title, description="", text=text)
    return PreparedSource(source=source, clean_text=text, published=None)


def test_tags_report_lists_distribution_and_marks_tagged_sources() -> None:
    topics = [
        Topic(id="health", label="Health", description="health health health health health"),
        Topic(id="startups", label="Startups", description="startup startup startup startup"),
    ]
    items = [
        item("https://x.test/h", "Health news", "health health health"),
        item("https://x.test/s", "Startup news", "startup startup startup"),
    ]
    report = tags_report(items, topics, KeywordEmbedder(), threshold=0.9, max_tags=3)
    assert "2 sources, 2 topics." in report
    assert "Score quantiles per topic:" in report
    assert "  >= 0.50:" in report
    assert "At threshold 0.90, max 3 tags: 2 tagged, 0 untagged." in report
    health_section = report.split("  health\n")[1].split("  startups")[0]
    assert health_section.splitlines()[0].lstrip().startswith("* ")
    assert "Health news" in health_section.splitlines()[0]
    assert health_section.splitlines()[1].lstrip().startswith("0.")
