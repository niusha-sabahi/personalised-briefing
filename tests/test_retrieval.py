from collections.abc import Sequence
from pathlib import Path

import pytest

from briefing.config import DEFAULT_CUTOFF_DATE, DEFAULT_LATEST_DATE
from briefing.models import PreparedSource, Source, Topic
from briefing.retrieval import (
    MAX_PASSAGE_CHARS,
    MIN_PASSAGE_CHARS,
    SelectedSource,
    TaggedSource,
    build_context,
    rank_passages,
    select_sources,
    split_passages,
    tag_corpus,
)
from briefing.sources import load_sources, prepare_sources, select_usable
from briefing.tagging import Tag

ROOT = Path(__file__).resolve().parent.parent


def prepared(url: str, text: str = "text", title: str = "Title") -> PreparedSource:
    source = Source(id=url, url=url, title=title, description="", text=text)
    return PreparedSource(source=source, clean_text=text, published=None)


def tagged(url: str, **scores: float) -> TaggedSource:
    """A source tagged with the given topic scores (keyword names use `_` for `-`)."""
    tags = sorted(
        (Tag(topic.replace("_", "-"), score) for topic, score in scores.items()),
        key=lambda t: (-t.score, t.topic_id),
    )
    return TaggedSource(prepared(url), tuple(tags))


def urls(selected: Sequence[SelectedSource]) -> list[str]:
    return [s.prepared.source.url for s in selected]


# --- select_sources (M3.4) ---------------------------------------------------------------


def test_candidates_are_the_union_of_the_personas_topics_ranked_by_best_score() -> None:
    corpus = [
        tagged("u/low", a=0.4),
        tagged("u/high", b=0.9),
        tagged("u/mid", a=0.5, b=0.6),
        tagged("u/other", z=0.99),  # carries no topic the persona follows
        tagged("u/none"),
    ]
    chosen = select_sources(corpus, ["a", "b"], top_k=10, per_topic_min=0)
    assert urls(chosen) == ["u/high", "u/mid", "u/low"]


def test_selected_source_keeps_only_the_personas_topics() -> None:
    chosen = select_sources([tagged("u/1", a=0.5, z=0.9)], ["a", "b"], top_k=5, per_topic_min=0)
    assert chosen[0].topics == (Tag("a", 0.5),)
    assert chosen[0].best_score == 0.5


def test_ties_are_broken_by_url_whatever_the_input_order() -> None:
    corpus = [tagged("u/c", a=0.5), tagged("u/a", a=0.5), tagged("u/b", a=0.5)]
    forward = select_sources(corpus, ["a"], top_k=2, per_topic_min=0)
    backward = select_sources(corpus[::-1], ["a"], top_k=2, per_topic_min=0)
    assert urls(forward) == urls(backward) == ["u/a", "u/b"]


def test_top_k_limits_the_selection() -> None:
    corpus = [tagged(f"u/{i}", a=0.5 + i / 100) for i in range(6)]
    assert urls(select_sources(corpus, ["a"], top_k=3, per_topic_min=0)) == ["u/5", "u/4", "u/3"]


def test_per_topic_minimum_stops_one_topic_crowding_out_another() -> None:
    corpus = [tagged(f"u/a{i}", a=0.9 - i / 100) for i in range(5)] + [tagged("u/b", b=0.4)]
    without = select_sources(corpus, ["a", "b"], top_k=3, per_topic_min=0)
    with_min = select_sources(corpus, ["a", "b"], top_k=3, per_topic_min=1)
    assert "u/b" not in urls(without)
    assert urls(with_min) == ["u/a0", "u/a1", "u/b"]


def test_a_source_chosen_for_one_topic_counts_for_every_topic_it_carries() -> None:
    corpus = [tagged("u/both", a=0.9, b=0.8), tagged("u/a", a=0.7), tagged("u/b", b=0.3)]
    chosen = select_sources(corpus, ["a", "b"], top_k=2, per_topic_min=1)
    # "u/both" satisfies both minimums, so the second place goes to the next best overall.
    assert urls(chosen) == ["u/both", "u/a"]


def test_minimum_uses_the_best_source_for_that_topic_not_overall_rank() -> None:
    corpus = [tagged("u/x", a=0.9, b=0.2), tagged("u/y", b=0.5)]
    chosen = select_sources(corpus, ["a", "b"], top_k=1, per_topic_min=1)
    assert urls(chosen) == ["u/x"]  # topic a goes first and u/x already counts for b too
    chosen = select_sources(corpus, ["b", "a"], top_k=1, per_topic_min=1)
    assert urls(chosen) == ["u/y"]


def test_topic_without_candidates_is_skipped() -> None:
    chosen = select_sources([tagged("u/a", a=0.5)], ["a", "b"], top_k=5, per_topic_min=2)
    assert urls(chosen) == ["u/a"]


def test_when_minimums_exceed_top_k_earlier_topics_win() -> None:
    corpus = [tagged("u/a", a=0.5), tagged("u/b", b=0.9), tagged("u/c", c=0.9)]
    chosen = select_sources(corpus, ["a", "b", "c"], top_k=2, per_topic_min=1)
    assert urls(chosen) == ["u/b", "u/a"]


def test_nothing_is_selected_without_tagged_sources() -> None:
    assert select_sources([tagged("u/1")], ["a"], top_k=5, per_topic_min=1) == []
    assert select_sources([], ["a"], top_k=5, per_topic_min=1) == []


# --- split_passages ----------------------------------------------------------------------


def para(label: str, length: int) -> str:
    text = f"{label} " * length
    return text[:length].strip() + "."


def test_empty_text_has_no_passages() -> None:
    assert split_passages("") == []
    assert split_passages("\n\n  \n\n") == []


def test_paragraphs_become_passages() -> None:
    text = f"{para('a', 300)}\n\n{para('b', 400)}"
    assert split_passages(text) == [para("a", 300), para("b", 400)]


def test_short_paragraphs_merge_into_the_next_one() -> None:
    body = para("b", 400)
    assert split_passages(f"## Heading\n\n{body}") == [f"## Heading\n\n{body}"]


def test_short_tail_joins_the_previous_passage_when_it_fits() -> None:
    body = para("a", 400)
    assert split_passages(f"{body}\n\nThe end.") == [f"{body}\n\nThe end."]


def test_short_tail_stands_alone_when_it_would_not_fit() -> None:
    body = para("a", MAX_PASSAGE_CHARS - 5)
    assert split_passages(f"{body}\n\nThe end.") == [body, "The end."]


def test_long_paragraph_is_split_at_sentence_ends() -> None:
    sentence = "This sentence is about forty characters." + " "
    text = sentence * 60
    passages = split_passages(text)
    assert len(passages) > 1
    assert all(len(p) <= MAX_PASSAGE_CHARS for p in passages)
    assert all(p.endswith(".") for p in passages)


def test_sentence_longer_than_the_limit_is_cut_at_a_word_break() -> None:
    passages = split_passages("word " * 1000)
    assert all(len(p) <= MAX_PASSAGE_CHARS for p in passages)
    assert " ".join(" ".join(passages).split()) == " ".join(["word"] * 1000)


def test_unbroken_run_is_cut_at_the_limit() -> None:
    passages = split_passages("x" * 3000)
    assert [len(p) for p in passages] == [MAX_PASSAGE_CHARS, MAX_PASSAGE_CHARS, 600]


def test_no_passage_exceeds_the_limit_when_merging_pieces() -> None:
    text = "\n\n".join([para("a", MIN_PASSAGE_CHARS - 1), para("b", MAX_PASSAGE_CHARS - 10)])
    assert all(len(p) <= MAX_PASSAGE_CHARS for p in split_passages(text))


def test_real_sources_split_without_losing_text_or_breaking_limits() -> None:
    sources = load_sources(ROOT / "sources_06-05-25.json")
    usable = select_usable(prepare_sources(sources, DEFAULT_LATEST_DATE), DEFAULT_CUTOFF_DATE)
    assert usable
    for item in usable:
        passages = split_passages(item.clean_text)
        assert passages
        assert all(0 < len(p) <= MAX_PASSAGE_CHARS for p in passages)
        assert " ".join(" ".join(passages).split()) == " ".join(item.clean_text.split())


# --- rank_passages -------------------------------------------------------------------------

TOPIC_VECTORS = [[1.0, 0.0], [0.0, 1.0]]
TOPIC_IDS = ["a", "b"]


def test_each_passage_goes_to_its_best_topic_in_document_order() -> None:
    vectors = [[0.0, 1.0], [1.0, 0.1], [0.9, 0.0]]
    matches = rank_passages(vectors, TOPIC_IDS, TOPIC_VECTORS, threshold=0.5, max_passages=5)
    assert [(m.index, m.topic_id) for m in matches] == [(0, "b"), (1, "a"), (2, "a")]


def test_passages_below_the_threshold_are_dropped() -> None:
    vectors = [[1.0, 1.0], [1.0, 0.0]]  # cosine against its best topic: 0.707 and 1.0
    kept = rank_passages(vectors, TOPIC_IDS, TOPIC_VECTORS, threshold=0.8, max_passages=5)
    assert [m.index for m in kept] == [1]


def test_score_equal_to_the_threshold_is_kept() -> None:
    kept = rank_passages([[1.0, 0.0]], TOPIC_IDS, TOPIC_VECTORS, threshold=1.0, max_passages=5)
    assert len(kept) == 1


def test_only_the_best_passages_are_kept_but_in_document_order() -> None:
    vectors = [[1.0, 0.5], [1.0, 0.0], [1.0, 0.25], [1.0, 0.9]]
    kept = rank_passages(vectors, TOPIC_IDS, TOPIC_VECTORS, threshold=0.0, max_passages=2)
    assert [m.index for m in kept] == [1, 2]


def test_tied_topics_go_to_the_earlier_one() -> None:
    kept = rank_passages([[1.0, 1.0]], TOPIC_IDS, TOPIC_VECTORS, threshold=0.0, max_passages=1)
    assert kept[0].topic_id == "a"


def test_no_passages_gives_no_matches() -> None:
    assert rank_passages([], TOPIC_IDS, TOPIC_VECTORS, threshold=0.0, max_passages=3) == []


# --- tag_corpus and build_context ------------------------------------------------------------


class KeywordEmbedder:
    """Vector = mentions of 'health' and 'startup' (plus a little noise-free offset)."""

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        return [
            [t.lower().count("health") + 0.01, t.lower().count("startup") + 0.01] for t in texts
        ]


TOPICS = [
    Topic(id="health", label="Health", description="health health health health health"),
    Topic(id="startups", label="Startups", description="startup startup startup startup"),
]


def test_tag_corpus_tags_each_source_by_similarity() -> None:
    items = [
        prepared("u/h", "health health health"),
        prepared("u/s", "startup startup startup"),
        prepared("u/none", "nothing relevant here at all"),
    ]
    result = tag_corpus(items, TOPICS, KeywordEmbedder(), threshold=0.9, max_tags=3)
    assert [[t.topic_id for t in r.tags] for r in result] == [["health"], ["startups"], []]
    assert [r.prepared.source.url for r in result] == ["u/h", "u/s", "u/none"]


def selected(url: str, text: str) -> SelectedSource:
    return SelectedSource(prepared(url, text), (Tag("health", 0.5),))


def test_build_context_keeps_relevant_passages_with_citable_ids() -> None:
    on_topic = "health " * 40
    off_topic = "weather and sport results " * 12
    text = f"{off_topic}\n\n{on_topic}\n\n{off_topic}\n\n{on_topic.replace('health', 'startup')}"
    context = build_context(
        [selected("u/1", text)], TOPICS, KeywordEmbedder(), threshold=0.9, max_passages=5
    )
    assert [p.id for p in context.passages] == ["s1p1", "s1p2"]
    assert [p.topic_id for p in context.passages] == ["health", "startups"]
    assert all(p.source_url == "u/1" for p in context.passages)
    assert all("weather" not in p.text for p in context.passages)


def test_source_without_a_relevant_passage_is_dropped_and_ids_renumbered() -> None:
    relevant = "health " * 40
    sources = [
        selected("u/boring", "weather and sport results " * 12),
        selected("u/good", relevant),
    ]
    context = build_context(sources, TOPICS, KeywordEmbedder(), threshold=0.9, max_passages=5)
    assert [s.prepared.source.url for s in context.sources] == ["u/good"]
    assert [p.id for p in context.passages] == ["s1p1"]


def test_build_context_with_nothing_selected_is_empty() -> None:
    context = build_context([], TOPICS, KeywordEmbedder(), threshold=0.5, max_passages=3)
    assert context.sources == () and context.passages == ()


@pytest.mark.parametrize("max_passages", [1, 2])
def test_build_context_respects_the_passage_cap(max_passages: int) -> None:
    text = "\n\n".join(["health " * 40] * 4)
    context = build_context(
        [selected("u/1", text)], TOPICS, KeywordEmbedder(), threshold=0.9, max_passages=max_passages
    )
    assert len(context.passages) == max_passages
