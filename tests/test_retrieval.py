from collections.abc import Sequence
from pathlib import Path

import pytest

from briefing.config import DEFAULT_CUTOFF_DATE, DEFAULT_LATEST_DATE
from briefing.models import PreparedSource, Source, Topic
from briefing.retrieval import (
    MAX_PASSAGE_CHARS,
    MIN_PASSAGE_CHARS,
    ChosenPassage,
    PassageCandidate,
    SelectedSource,
    TaggedSource,
    build_context,
    choose_passages,
    gather_candidates,
    is_boilerplate,
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


def test_a_chosen_source_counts_only_for_the_topic_it_matches_best() -> None:
    corpus = [tagged("u/both", a=0.9, b=0.8), tagged("u/a", a=0.7), tagged("u/b", b=0.3)]
    chosen = select_sources(corpus, ["a", "b"], top_k=2, per_topic_min=1)
    # "u/both" is mainly about a and merely mentions b, so b still gets a source of its own,
    # even though u/a would rank higher overall.
    assert urls(chosen) == ["u/both", "u/b"]


def test_a_weak_carrier_does_not_satisfy_a_topics_minimum() -> None:
    corpus = [
        tagged("u/p1", pharma=0.55, equity=0.31),
        tagged("u/p2", pharma=0.54, equity=0.32),
        tagged("u/p3", pharma=0.53),
        tagged("u/equity", equity=0.49),
    ]
    chosen = select_sources(corpus, ["pharma", "equity"], top_k=3, per_topic_min=1)
    assert "u/equity" in urls(chosen)


def test_a_non_primary_carrier_fills_a_topic_with_no_primary_source() -> None:
    corpus = [tagged("u/x", a=0.9, b=0.5), tagged("u/y", a=0.8)]
    chosen = select_sources(corpus, ["a", "b"], top_k=1, per_topic_min=1)
    assert urls(chosen) == ["u/x"]  # top_k reached by topic a
    chosen = select_sources(corpus, ["a", "b"], top_k=2, per_topic_min=1)
    assert urls(chosen) == [
        "u/x",
        "u/y",
    ]  # b has no primary source, u/x carries it but counts for a
    chosen = select_sources(corpus, ["b", "a"], top_k=1, per_topic_min=1)
    assert urls(chosen) == ["u/x"]  # b takes its best carrier


def test_every_topic_gets_a_source_before_any_topic_gets_a_second() -> None:
    corpus = [
        tagged("u/a1", a=0.9),
        tagged("u/a2", a=0.8),
        tagged("u/b1", b=0.7),
        tagged("u/b2", b=0.6),
        tagged("u/c1", c=0.5),
        tagged("u/c2", c=0.4),
    ]
    chosen = select_sources(corpus, ["a", "b", "c"], top_k=4, per_topic_min=2)
    # Round one gives a, b and c a source each, and only then does a get its second.
    assert urls(chosen) == ["u/a1", "u/a2", "u/b1", "u/c1"]


def test_a_second_minimum_brings_in_a_dedicated_source() -> None:
    corpus = [
        tagged("u/ai1", ai=0.6),
        tagged("u/ai2", ai=0.59),
        tagged("u/ai3", ai=0.58),
        tagged("u/mixed", vc=0.41, ai=0.40),  # mainly venture capital by a hair
        tagged("u/vc", vc=0.38),
    ]
    one = select_sources(corpus, ["ai", "vc"], top_k=4, per_topic_min=1)
    two = select_sources(corpus, ["ai", "vc"], top_k=4, per_topic_min=2)
    assert "u/vc" not in urls(one)
    assert "u/vc" in urls(two)


def test_sources_taken_to_fill_a_topic_count_for_its_later_rounds() -> None:
    # b has no primary source: round one takes its best carrier, round two its next.
    corpus = [tagged("u/x", a=0.9, b=0.5), tagged("u/y", a=0.8, b=0.45), tagged("u/z", a=0.7)]
    chosen = select_sources(corpus, ["a", "b"], top_k=3, per_topic_min=2)
    assert urls(chosen) == ["u/x", "u/y", "u/z"]
    chosen = select_sources(corpus, ["b", "a"], top_k=2, per_topic_min=2)
    assert urls(chosen) == ["u/x", "u/y"]


def test_minimum_uses_the_best_source_for_that_topic_not_overall_rank() -> None:
    corpus = [tagged("u/x", a=0.9, b=0.2), tagged("u/y", b=0.5)]
    chosen = select_sources(corpus, ["a", "b"], top_k=1, per_topic_min=1)
    assert urls(chosen) == ["u/x"]  # topic a goes first and fills the only place
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


# --- is_boilerplate (M8) ---------------------------------------------------------------------

PROSE = (
    "Health officials said coverage rose again this spring, and several states reported that "
    "enrolment in the programme grew faster than they had forecast when the budget was set."
)


@pytest.mark.parametrize(
    "passage",
    [
        # A run of related-article links whose Markdown was left half cleaned.
        "Closing the gap: Fair victim compensation in the EU AI liability regime]"
        "(https://example.test/2025/05/05/closing-the-gap) Towards Comprehensive Regulation]"
        "(https://example.test/2025/05/02/towards-comprehensive-regulation)",
        # Mostly address.
        "https://www.example.test/story/doge-data-access-hhs/4/21 CMS Integrated Data Repository",
        "These cookies are necessary for the website to function and cannot be switched off.",
        "MMWR and Morbidity and Mortality Weekly Report are service marks of the U.S. "
        "Department of Health and Human Services.",
        "References to non-CDC sites on the Internet are provided as a service to MMWR readers "
        "and do not constitute or imply endorsement of these organizations or their programs.",
        PROSE + " Read our privacy policy and the terms of use before you continue to browse.",
        "1\\. Kiang MV, Bubar KM, Maldonado Y, et al. Modeling reemergence of vaccine-eliminated "
        "infectious diseases under declining vaccination in the US. JAMA. 2025;333:1-8.",
        "08. CDC. Assessing measles outbreak risk in the United States. Atlanta, GA: US "
        "Department of Health and Human Services; 2024.",
    ],
)
def test_page_furniture_is_boilerplate(passage: str) -> None:
    assert is_boilerplate(passage)


@pytest.mark.parametrize(
    "passage",
    [
        PROSE,
        # Real news that happens to contain words found in page furniture.
        "A federal judge questioned fair use in the copyright lawsuit against the AI company, "
        "asking both sides how training on books differs from a person reading them.",
        f"{PROSE} {PROSE} Some sites also use cookies to remember readers, which regulators "
        "now examine.",
        # One stray link fragment in otherwise long prose.
        PROSE + " (see the analysis](https://example.test/analysis) for the full methodology)",
        "2. **Results chain**: a diagram showing the main results that interventions are "
        "expected to achieve in the given thematic area.",
    ],
)
def test_ordinary_content_is_not_boilerplate(passage: str) -> None:
    assert not is_boilerplate(passage)


def real_usable_passages() -> list[str]:
    sources = load_sources(ROOT / "sources_06-05-25.json")
    usable = select_usable(prepare_sources(sources, DEFAULT_LATEST_DATE), DEFAULT_CUTOFF_DATE)
    return [p for item in usable for p in split_passages(item.clean_text)]


def test_real_page_furniture_is_caught_and_real_content_is_kept() -> None:
    passages = real_usable_passages()
    junk = [
        "08. CDC. Assessing measles outbreak risk",
        "References to non-CDC sites",
        "are service marks",
        "Asembia AXS25: Strategic Partnerships",
        "Community Pharmacies Actively Advance",
    ]
    content = [
        "To put it in perspective, consider the per-query costs",
        "Hopes for a renewed US-UK trade agreement remain alive",
        "Newcomers to the list include $2.5 billion-valued Anysphere",
    ]
    for needle in junk:
        matching = [p for p in passages if needle in p]
        assert matching, needle
        assert all(is_boilerplate(p) for p in matching), needle
    for needle in content:
        matching = [p for p in passages if needle in p]
        assert matching, needle
        assert not any(is_boilerplate(p) for p in matching), needle
    share = sum(is_boilerplate(p) for p in passages) / len(passages)
    assert 0.05 < share < 0.40, share  # a sanity band: not a no-op, and not eating the corpus


# --- choose_passages -------------------------------------------------------------------------

TOPIC_IDS = ["a", "b"]


def candidate(source: int, position: int, *scores: float) -> PassageCandidate:
    return PassageCandidate(source, position, f"text {source}.{position}", tuple(scores))


def picked(chosen: Sequence[ChosenPassage]) -> list[tuple[int, int, str]]:
    return [(p.candidate.source_index, p.candidate.position, p.topic_id) for p in chosen]


def choose(
    candidates: Sequence[PassageCandidate],
    threshold: float = 0.4,
    per_topic: int = 2,
    per_source: int = 9,
) -> list[ChosenPassage]:
    return choose_passages(candidates, TOPIC_IDS, threshold, per_topic, per_source)


def test_each_topic_takes_its_best_passages_and_results_are_in_document_order() -> None:
    candidates = [candidate(0, 0, 0.9, 0.1), candidate(0, 1, 0.2, 0.8), candidate(1, 0, 0.7, 0.6)]
    assert picked(choose(candidates, per_topic=1)) == [(0, 0, "a"), (0, 1, "b")]


def test_a_passage_serves_one_topic_only() -> None:
    candidates = [candidate(0, 0, 0.9, 0.9), candidate(0, 1, 0.1, 0.5)]
    assert picked(choose(candidates, per_topic=1)) == [(0, 0, "a"), (0, 1, "b")]


def test_a_topic_is_not_crowded_out_by_a_dominant_neighbour() -> None:
    candidates = [candidate(0, i, 0.9, 0.5) for i in range(4)]
    chosen = choose(candidates, per_topic=2)
    assert [p.topic_id for p in chosen].count("a") == 2
    assert [p.topic_id for p in chosen].count("b") == 2


def test_a_passage_about_a_minor_topic_is_used_for_it_inside_a_major_topic_article() -> None:
    # The funding passage scores higher for "a" than for "b", but "a" has a better passage.
    candidates = [candidate(0, 0, 0.9, 0.1), candidate(0, 1, 0.6, 0.45)]
    assert picked(choose(candidates, per_topic=1)) == [(0, 0, "a"), (0, 1, "b")]


def test_score_equal_to_the_threshold_qualifies_and_below_does_not() -> None:
    candidates = [candidate(0, 0, 0.4, 0.0), candidate(0, 1, 0.3999, 0.0)]
    assert picked(choose(candidates, threshold=0.4)) == [(0, 0, "a")]


def test_no_source_supplies_more_than_the_per_source_limit() -> None:
    candidates = [candidate(0, i, 0.9 - i / 100, 0.9 - i / 100) for i in range(4)]
    candidates.append(candidate(1, 0, 0.5, 0.5))
    chosen = choose(candidates, per_topic=3, per_source=2)
    assert [p.candidate.source_index for p in chosen].count(0) == 2
    assert (1, 0) in {(p.candidate.source_index, p.candidate.position) for p in chosen}


def test_a_topic_draws_on_several_sources_when_one_source_dominates_it() -> None:
    candidates = [candidate(0, i, 0.9 - i / 100, 0.0) for i in range(4)]
    candidates.append(candidate(1, 0, 0.5, 0.0))
    capped = choose_passages(candidates, TOPIC_IDS, 0.4, 3, 9, per_source_per_topic=2)
    uncapped = choose_passages(candidates, TOPIC_IDS, 0.4, 3, 9)
    assert picked(capped) == [(0, 0, "a"), (0, 1, "a"), (1, 0, "a")]
    assert picked(uncapped) == [(0, 0, "a"), (0, 1, "a"), (0, 2, "a")]


def test_the_per_source_per_topic_limit_applies_to_each_topic_separately() -> None:
    candidates = [
        candidate(0, 0, 0.9, 0.0),
        candidate(0, 1, 0.8, 0.0),
        candidate(0, 2, 0.0, 0.9),
        candidate(0, 3, 0.0, 0.8),
    ]
    chosen = choose_passages(candidates, TOPIC_IDS, 0.4, 3, 9, per_source_per_topic=2)
    assert picked(chosen) == [(0, 0, "a"), (0, 1, "a"), (0, 2, "b"), (0, 3, "b")]


def test_the_overall_per_source_limit_still_applies_with_a_per_topic_limit() -> None:
    candidates = [
        candidate(0, 0, 0.9, 0.0),
        candidate(0, 1, 0.8, 0.0),
        candidate(0, 2, 0.0, 0.9),
        candidate(0, 3, 0.0, 0.8),
    ]
    chosen = choose_passages(candidates, TOPIC_IDS, 0.4, 3, 3, per_source_per_topic=2)
    assert len(chosen) == 3


def test_a_passage_that_qualifies_for_several_topics_goes_to_the_earlier_one() -> None:
    assert picked(choose([candidate(0, 0, 0.8, 0.8)], per_topic=1)) == [(0, 0, "a")]


def test_nothing_qualifying_means_nothing_chosen() -> None:
    assert choose([candidate(0, 0, 0.2, 0.3)]) == []
    assert choose([]) == []


def test_ties_are_broken_by_document_order() -> None:
    candidates = [candidate(1, 0, 0.7, 0.0), candidate(0, 3, 0.7, 0.0), candidate(0, 1, 0.7, 0.0)]
    assert picked(choose(candidates, per_topic=2)) == [(0, 1, "a"), (0, 3, "a")]


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


def context_for(
    sources: Sequence[SelectedSource], per_topic: int = 5, per_source: int = 5
) -> tuple[list[str], list[tuple[str, str, str]]]:
    context = build_context(
        sources,
        TOPICS,
        KeywordEmbedder(),
        threshold=0.9,
        per_topic=per_topic,
        per_source=per_source,
    )
    kept = [s.prepared.source.url for s in context.sources]
    return kept, [(p.id, p.topic_id, p.source_url) for p in context.passages]


def test_build_context_keeps_relevant_passages_with_citable_ids() -> None:
    on_topic = "health " * 40
    off_topic = "weather and sport results " * 12
    text = f"{off_topic}\n\n{on_topic}\n\n{off_topic}\n\n{on_topic.replace('health', 'startup')}"
    context = build_context(
        [selected("u/1", text)], TOPICS, KeywordEmbedder(), 0.9, per_topic=5, per_source=5
    )
    assert [(p.id, p.topic_id) for p in context.passages] == [
        ("s1p1", "health"),
        ("s1p2", "startups"),
    ]
    assert all(p.source_url == "u/1" for p in context.passages)
    assert all("weather" not in p.text for p in context.passages)


def test_source_without_a_relevant_passage_is_dropped_and_ids_renumbered() -> None:
    sources = [
        selected("u/boring", "weather and sport results " * 12),
        selected("u/good", "health " * 40),
    ]
    kept, passages = context_for(sources)
    assert kept == ["u/good"]
    assert [p[0] for p in passages] == ["s1p1"]


def test_build_context_with_nothing_selected_is_empty() -> None:
    assert context_for([]) == ([], [])


@pytest.mark.parametrize("limit", [1, 2])
def test_build_context_respects_the_per_source_and_per_topic_limits(limit: int) -> None:
    text = "\n\n".join(["health " * 40] * 4)
    assert len(context_for([selected("u/1", text)], per_source=limit)[1]) == limit
    assert len(context_for([selected("u/1", text)], per_topic=limit)[1]) == limit


def test_build_context_applies_the_per_source_per_topic_limit() -> None:
    text = "\n\n".join(["health " * 40] * 4)
    context = build_context(
        [selected("u/1", text)],
        TOPICS,
        KeywordEmbedder(),
        0.9,
        per_topic=5,
        per_source=5,
        per_source_per_topic=2,
    )
    assert len(context.passages) == 2


def test_page_furniture_never_reaches_the_context() -> None:
    banner = "health " * 40 + "This site uses cookies. Read our privacy policy."
    text = f"{banner}\n\n{'health ' * 40}"
    _, passages = context_for([selected("u/1", text)])
    assert len(passages) == 1


def test_gather_candidates_drops_boilerplate_before_embedding() -> None:
    banner = "health " * 40 + "This site uses cookies. Read our privacy policy."
    embedder = KeywordEmbedder()
    embedded: list[str] = []
    original = embedder.embed

    def spy(texts: Sequence[str]) -> list[list[float]]:
        embedded.extend(texts)
        return original(texts)

    embedder.embed = spy  # type: ignore[method-assign]
    found = gather_candidates([selected("u/1", f"{banner}\n\n{'startup ' * 40}")], TOPICS, embedder)
    assert len(found) == 1 and found[0].scores[1] > found[0].scores[0]
    assert not any("cookies" in text for text in embedded)
