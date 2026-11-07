"""Check the model's draft against the real passages and render safe, fully cited Markdown.

Pure functions only. The model's text is never trusted: its citations are looked up in the
passage table, its words are reduced to plain text, and every link in the output comes from
the source table, never from the model (M7, S8, S14).
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from briefing.models import (
    BriefingDraft,
    BriefingSource,
    Passage,
    Persona,
    Topic,
)

_URL_IN_TEXT = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_CITATION_NUMBER = re.compile(r"\[\d+\]")
_URL_IN_MARKDOWN = re.compile(r"https?://[^\s)<>\]]+")


@dataclass(frozen=True)
class CheckedBullet:
    """A bullet whose text is plain and whose citations all exist."""

    text: str
    passages: tuple[Passage, ...]


@dataclass(frozen=True)
class CheckedSection:
    """A topic's surviving bullets."""

    topic_id: str
    bullets: tuple[CheckedBullet, ...]


@dataclass(frozen=True)
class CheckedDraft:
    """The draft after validation, with counts of what was removed (for logging)."""

    sections: tuple[CheckedSection, ...]
    dropped_bullets: int
    dropped_citations: int


def plain_text(text: str) -> str:
    """Reduce model text to one line of plain prose.

    Removes URLs and `[n]` markers (citations come only from `passage_ids`) and collapses
    all whitespace, so a bullet cannot carry its own links or start a heading or list.
    """
    text = _URL_IN_TEXT.sub("", text)
    text = _CITATION_NUMBER.sub("", text)
    return " ".join(text.split())


def validate_draft(
    draft: BriefingDraft, passages: Sequence[Passage], topic_order: Sequence[str]
) -> CheckedDraft:
    """Keep only bullets that are traceable to real passages on the section's topic (S14, M8).

    A citation to an unknown passage id is removed. A bullet is dropped when no valid
    citation remains, when none of its cited passages belongs to the section's topic, when
    its text is empty, or when its section is not one of the persona's topics. Sections
    come out in `topic_order`, and a topic named twice is merged.
    """
    by_id = {passage.id: passage for passage in passages}
    kept: dict[str, list[CheckedBullet]] = {topic_id: [] for topic_id in topic_order}
    dropped_bullets = 0
    dropped_citations = 0
    for section in draft.sections:
        if section.topic_id not in kept:
            dropped_bullets += len(section.bullets)
            continue
        for bullet in section.bullets:
            unique_ids = list(dict.fromkeys(bullet.passage_ids))
            cited = tuple(by_id[i] for i in unique_ids if i in by_id)
            dropped_citations += len(unique_ids) - len(cited)
            text = plain_text(bullet.text)
            on_topic = any(p.topic_id == section.topic_id for p in cited)
            if text and on_topic:
                kept[section.topic_id].append(CheckedBullet(text, cited))
            else:
                dropped_bullets += 1
    sections = tuple(
        CheckedSection(topic_id, tuple(bullets)) for topic_id, bullets in kept.items() if bullets
    )
    return CheckedDraft(sections, dropped_bullets, dropped_citations)


def _escape(text: str) -> str:
    """Escape Markdown and HTML punctuation so text renders literally."""
    text = text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    # A leading marker would turn the text into a heading, list item or numbered list.
    text = re.sub(r"^([#*+\-])", r"\\\1", text)
    return re.sub(r"^(\d+)([.)])", r"\1\\\2", text)


def _safe_url(url: str) -> str:
    """Percent-encode the characters that would end a Markdown link target early."""
    for char, code in ((" ", "%20"), ("(", "%28"), (")", "%29"), ("<", "%3C"), (">", "%3E")):
        url = url.replace(char, code)
    return url


def render_markdown(
    persona: Persona,
    topics: Sequence[Topic],
    checked: CheckedDraft,
    source_titles: Mapping[str, str],
) -> tuple[str, list[BriefingSource]]:
    """Render the checked draft as Markdown with numbered citations and a Sources list (M6, M7).

    Args:
        persona: Who the briefing is for (used in the title).
        topics: The persona's topics, for section headings.
        checked: Output of `validate_draft`.
        source_titles: Title of each source, by URL.

    Returns:
        The Markdown, and the cited sources in citation-number order. Numbers follow the
        order of first citation, and only sources that are cited are listed.
    """
    labels = {topic.id: topic.label for topic in topics}
    numbers: dict[str, int] = {}
    lines = [f"# Briefing: {_escape(persona.position)}, {_escape(persona.location)}", ""]
    for section in checked.sections:
        lines += [f"## {_escape(labels[section.topic_id])}", ""]
        for bullet in section.bullets:
            urls = list(dict.fromkeys(p.source_url for p in bullet.passages))
            for url in urls:
                numbers.setdefault(url, len(numbers) + 1)
            ordered = sorted(urls, key=lambda u: numbers[u])
            links = " ".join(f"[\\[{numbers[u]}\\]]({_safe_url(u)})" for u in ordered)
            lines.append(f"- {_escape(bullet.text)} {links}")
        lines.append("")

    sources = [
        BriefingSource(
            number=number, title=plain_text(source_titles[url]) or "Untitled source", url=url
        )
        for url, number in numbers.items()
    ]
    lines += ["## Sources", ""]
    lines += [f"{s.number}. [{_escape(s.title)}]({_safe_url(s.url)})" for s in sources]
    return "\n".join(lines) + "\n", sources


def foreign_urls(markdown: str, allowed_urls: Sequence[str]) -> list[str]:
    """Return every URL in `markdown` that is not one of `allowed_urls` (S14).

    A final guard over the rendered output. It should always be empty, because links are
    rendered from the source table, so a non-empty result means a bug or an escaping gap.
    """
    allowed = {_safe_url(url) for url in allowed_urls}
    return [url for url in _URL_IN_MARKDOWN.findall(markdown) if url not in allowed]
