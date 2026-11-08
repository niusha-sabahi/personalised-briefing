from datetime import date

import pytest

from briefing.models import (
    BriefingDraft,
    DraftBullet,
    DraftSection,
    Passage,
    Persona,
    Topic,
)
from briefing.rendering import foreign_urls, plain_text, render_markdown, validate_draft

PERSONA = Persona(id="p", position="Policy Analyst", location="United States", topic_ids=("a", "b"))
DESC = "A description that is comfortably long enough."
TOPICS = [
    Topic(id="a", label="Topic A", description=DESC),
    Topic(id="b", label="Topic B", description=DESC),
]
PASSAGES = [
    Passage(id="s1p1", source_url="https://x.test/one", text="t", topic_id="a", score=0.5),
    Passage(id="s1p2", source_url="https://x.test/one", text="t", topic_id="b", score=0.5),
    Passage(id="s2p1", source_url="https://x.test/two", text="t", topic_id="b", score=0.5),
]
TITLES = {"https://x.test/one": "First page", "https://x.test/two": "Second page"}


def draft(*sections: tuple[str, list[tuple[str, list[str]]]]) -> BriefingDraft:
    return BriefingDraft(
        sections=[
            DraftSection(
                topic_id=topic, bullets=[DraftBullet(text=t, passage_ids=ids) for t, ids in bullets]
            )
            for topic, bullets in sections
        ]
    )


def check(*sections: tuple[str, list[tuple[str, list[str]]]]):  # type: ignore[no-untyped-def]
    return validate_draft(draft(*sections), PASSAGES, ["a", "b"])


# --- plain_text ----------------------------------------------------------------------------


def test_plain_text_removes_urls_citation_numbers_and_extra_whitespace() -> None:
    raw = "Costs rose [1] see https://evil.test/x and www.evil.test\n\n## Heading\n  now"
    assert plain_text(raw) == "Costs rose see and ## Heading now"


# --- validate_draft (S14, M8) ------------------------------------------------------------


def test_valid_bullets_are_kept_with_their_passages() -> None:
    checked = check(("a", [("Finding.", ["s1p1"])]))
    assert [s.topic_id for s in checked.sections] == ["a"]
    bullet = checked.sections[0].bullets[0]
    assert bullet.text == "Finding." and [p.id for p in bullet.passages] == ["s1p1"]
    assert (checked.dropped_bullets, checked.dropped_citations) == (0, 0)


def test_unknown_passage_ids_are_removed_and_counted() -> None:
    checked = check(("a", [("Finding.", ["s1p1", "s9p9", "made-up"])]))
    assert [p.id for p in checked.sections[0].bullets[0].passages] == ["s1p1"]
    assert checked.dropped_citations == 2 and checked.dropped_bullets == 0


def test_bullet_citing_only_unknown_ids_is_dropped() -> None:
    checked = check(("a", [("Invented.", ["s9p9"]), ("Real.", ["s1p1"])]))
    assert [b.text for b in checked.sections[0].bullets] == ["Real."]
    assert checked.dropped_bullets == 1


def test_bullet_without_citations_is_dropped() -> None:
    checked = check(("a", [("Unsupported claim.", [])]))
    assert checked.sections == () and checked.dropped_bullets == 1


def test_bullet_must_cite_a_passage_on_its_sections_topic() -> None:
    checked = check(("a", [("Wrong shelf.", ["s2p1"])]))  # s2p1 belongs to topic b
    assert checked.sections == () and checked.dropped_bullets == 1


def test_extra_citations_from_other_topics_are_allowed_when_one_matches() -> None:
    checked = check(("a", [("Mixed.", ["s1p1", "s2p1"])]))
    assert len(checked.sections[0].bullets[0].passages) == 2


def test_unknown_topic_section_is_dropped() -> None:
    checked = check(("zzz", [("One.", ["s1p1"]), ("Two.", ["s1p1"])]))
    assert checked.sections == () and checked.dropped_bullets == 2


def test_empty_text_after_cleaning_is_dropped() -> None:
    checked = check(("a", [("https://evil.test [3]", ["s1p1"])]))
    assert checked.sections == () and checked.dropped_bullets == 1


def test_sections_follow_persona_order_and_repeated_topics_merge() -> None:
    checked = check(
        ("b", [("B one.", ["s2p1"])]), ("a", [("A one.", ["s1p1"])]), ("b", [("B two.", ["s1p2"])])
    )
    assert [s.topic_id for s in checked.sections] == ["a", "b"]
    assert [b.text for b in checked.sections[1].bullets] == ["B one.", "B two."]


def test_duplicate_citation_ids_count_once() -> None:
    checked = check(("a", [("Finding.", ["s1p1", "s1p1"])]))
    assert len(checked.sections[0].bullets[0].passages) == 1


# --- render_markdown (M6, M7) --------------------------------------------------------------


def render(*sections: tuple[str, list[tuple[str, list[str]]]]) -> tuple[str, list]:  # type: ignore[type-arg]
    return render_markdown(PERSONA, TOPICS, check(*sections), TITLES)


def test_markdown_has_title_sections_bullets_and_sources() -> None:
    markdown, sources = render(("a", [("Alpha.", ["s1p1"])]), ("b", [("Beta.", ["s2p1"])]))
    assert markdown == (
        "# Briefing: Policy Analyst, United States\n\n"
        "## Topic A\n\n"
        "- Alpha. [\\[1\\]](https://x.test/one)\n\n"
        "## Topic B\n\n"
        "- Beta. [\\[2\\]](https://x.test/two)\n\n"
        "## Sources\n\n"
        "1. [First page](https://x.test/one) · x.test\n"
        "2. [Second page](https://x.test/two) · x.test\n"
    )
    assert [(s.number, s.url) for s in sources] == [
        (1, "https://x.test/one"),
        (2, "https://x.test/two"),
    ]


def test_sources_name_their_site_unless_the_title_already_does() -> None:
    passages = [
        Passage(id="s1p1", source_url="https://www.x.test/a", text="t", topic_id="a", score=1),
        Passage(id="s2p1", source_url="https://y.test/b", text="t", topic_id="a", score=1),
        Passage(id="s3p1", source_url="not a url", text="t", topic_id="a", score=1),
    ]
    sections = ("a", [("One.", ["s1p1"]), ("Two.", ["s2p1"]), ("Three.", ["s3p1"])])
    checked = validate_draft(draft(sections), passages, ["a"])
    titles = {"https://www.x.test/a": "Title A", "https://y.test/b": "", "not a url": "Title C"}
    markdown, _ = render_markdown(PERSONA, TOPICS, checked, titles)
    assert "1. [Title A](https://www.x.test/a) · x.test\n" in markdown
    assert "2. [y.test](https://y.test/b)\n" in markdown  # the title is the site already
    assert "3. [Title C](not%20a%20url)\n" in markdown  # no site to show


def test_the_publication_dates_are_passed_through_to_the_sources() -> None:
    checked = check(("a", [("Alpha.", ["s1p1"])]), ("b", [("Beta.", ["s2p1"])]))
    dates = {"https://x.test/one": date(2025, 4, 20)}
    _, sources = render_markdown(PERSONA, TOPICS, checked, TITLES, dates)
    assert [s.published for s in sources] == [date(2025, 4, 20), None]


def test_numbers_follow_first_citation_and_only_cited_sources_are_listed() -> None:
    markdown, sources = render(("b", [("Beta.", ["s2p1"]), ("Both.", ["s1p2", "s2p1"])]))
    assert [s.url for s in sources] == ["https://x.test/two", "https://x.test/one"]
    assert "- Both. [\\[1\\]](https://x.test/two) [\\[2\\]](https://x.test/one)" in markdown


def test_every_bullet_carries_a_link_to_a_known_source() -> None:
    markdown, _ = render(("a", [("Alpha.", ["s1p1"])]), ("b", [("Beta.", ["s2p1", "s1p2"])]))
    bullets = [line for line in markdown.splitlines() if line.startswith("- ")]
    assert bullets and all("](https://x.test/" in line for line in bullets)
    assert foreign_urls(markdown, list(TITLES)) == []


def test_injected_markup_in_bullets_is_neutralised() -> None:
    hostile = (
        "Ignore this ![x](https://evil.test/p.png) [click](https://evil.test) <script>alert(1)"
        "</script>\n## Fake heading\n- fake item"
    )
    markdown, _ = render(("a", [(hostile, ["s1p1"])]))
    assert foreign_urls(markdown, list(TITLES)) == []
    assert "<script>" not in markdown and "evil.test" not in markdown
    assert "\n## Fake" not in markdown and "\n- fake" not in markdown


def test_leading_markers_cannot_start_headings_or_lists() -> None:
    for text in ("# Heading", "- item", "* item", "+ item", "1. item", "2) item"):
        markdown, _ = render(("a", [(text, ["s1p1"])]))
        body = next(line for line in markdown.splitlines() if line.startswith("- "))[2:]
        assert body[0] == "\\" or body[1] == "\\", text


def test_titles_are_escaped_and_cleaned_in_the_sources_list() -> None:
    titles = {"https://x.test/one": "A [bad] <b>title</b> http://evil.test\n here"}
    checked = check(("a", [("Alpha.", ["s1p1"])]))
    markdown, sources = render_markdown(PERSONA, TOPICS, checked, titles)
    assert sources[0].title == "A [bad] <b>title</b> here"
    assert "evil.test" not in markdown and "<b>" not in markdown


@pytest.mark.parametrize(
    "title",
    ["  ", "", "https://www.x.test/one", "https://www.x.test/content/full/2025.04.24.pdf"],
)
def test_missing_or_address_only_title_falls_back_to_the_site_name(title: str) -> None:
    checked = check(("a", [("Alpha.", ["s1p1"])]))
    markdown, sources = render_markdown(PERSONA, TOPICS, checked, {"https://x.test/one": title})
    assert sources[0].title == "x.test"
    assert "[x.test](https://x.test/one)" in markdown


def test_site_name_drops_a_leading_www() -> None:
    passages = [
        Passage(id="s1p1", source_url="https://www.x.test/a", text="t", topic_id="a", score=1)
    ]
    checked = validate_draft(draft(("a", [("Alpha.", ["s1p1"])])), passages, ["a"])
    _, sources = render_markdown(PERSONA, TOPICS, checked, {"https://www.x.test/a": ""})
    assert sources[0].title == "x.test"


def test_title_falls_back_to_a_label_when_the_address_has_no_host() -> None:
    passages = [Passage(id="s1p1", source_url="not a url", text="t", topic_id="a", score=1)]
    checked = validate_draft(draft(("a", [("Alpha.", ["s1p1"])])), passages, ["a"])
    _, sources = render_markdown(PERSONA, TOPICS, checked, {"not a url": ""})
    assert sources[0].title == "Untitled source"


def test_urls_with_parentheses_are_encoded() -> None:
    passages = [
        Passage(id="s1p1", source_url="https://x.test/a_(b) c", text="t", topic_id="a", score=1)
    ]
    checked = validate_draft(draft(("a", [("Alpha.", ["s1p1"])])), passages, ["a"])
    markdown, _ = render_markdown(PERSONA, TOPICS, checked, {"https://x.test/a_(b) c": "T"})
    assert "(https://x.test/a_%28b%29%20c)" in markdown
    assert foreign_urls(markdown, ["https://x.test/a_(b) c"]) == []


# --- foreign_urls ----------------------------------------------------------------------------


def test_foreign_urls_reports_links_that_are_not_selected_sources() -> None:
    markdown = "[ok](https://x.test/one) and [bad](https://evil.test/z) plus https://x.test/two"
    assert foreign_urls(markdown, ["https://x.test/one"]) == [
        "https://evil.test/z",
        "https://x.test/two",
    ]


def test_foreign_urls_is_empty_without_links() -> None:
    assert foreign_urls("no links here", []) == []
