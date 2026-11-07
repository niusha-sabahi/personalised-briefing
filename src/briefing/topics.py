"""Topic taxonomy and persona definitions, loaded from YAML and validated at startup."""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from briefing.models import Persona, Topic


class TaxonomyError(Exception):
    """The topics or personas file is missing, malformed or inconsistent."""


@dataclass(frozen=True)
class Taxonomy:
    """The validated topics and personas, in file order."""

    topics: tuple[Topic, ...]
    personas: tuple[Persona, ...]

    def topic(self, topic_id: str) -> Topic | None:
        """Return the topic with this id, or None."""
        return next((t for t in self.topics if t.id == topic_id), None)

    def persona(self, persona_id: str) -> Persona | None:
        """Return the persona with this id, or None."""
        return next((p for p in self.personas if p.id == persona_id), None)


def _read_list(path: Path, key: str) -> list[object]:
    """Read a YAML file shaped like `{key: [...]}` and return the list."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise TaxonomyError(f"Cannot read {path}: {exc}") from exc
    items = data.get(key) if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise TaxonomyError(f"{path} must contain a non-empty list under '{key}'")
    return items


def _duplicates(values: list[str]) -> list[str]:
    """Return the values that appear more than once, sorted."""
    return sorted(value for value, count in Counter(values).items() if count > 1)


def load_topics(path: Path) -> tuple[Topic, ...]:
    """Load and validate the topic taxonomy.

    Raises:
        TaxonomyError: If the file is unreadable, an entry is invalid, or ids repeat.
    """
    try:
        topics = tuple(Topic.model_validate(item) for item in _read_list(path, "topics"))
    except ValidationError as exc:
        raise TaxonomyError(f"Invalid topic in {path}: {exc}") from exc
    if duplicated := _duplicates([t.id for t in topics]):
        raise TaxonomyError(f"Duplicate topic id(s) in {path}: {', '.join(duplicated)}")
    return topics


def load_personas(path: Path, topics: tuple[Topic, ...]) -> tuple[Persona, ...]:
    """Load and validate personas against the known topics.

    Raises:
        TaxonomyError: If the file is unreadable, an entry is invalid, persona ids
            repeat, a persona repeats a topic, or a persona names an unknown topic.
    """
    try:
        personas = tuple(Persona.model_validate(item) for item in _read_list(path, "personas"))
    except ValidationError as exc:
        raise TaxonomyError(f"Invalid persona in {path}: {exc}") from exc
    if duplicated := _duplicates([p.id for p in personas]):
        raise TaxonomyError(f"Duplicate persona id(s) in {path}: {', '.join(duplicated)}")

    known = {t.id for t in topics}
    for persona in personas:
        if repeated := _duplicates(list(persona.topic_ids)):
            raise TaxonomyError(
                f"Persona '{persona.id}' repeats topic id(s): {', '.join(repeated)}"
            )
        if unknown := sorted(set(persona.topic_ids) - known):
            raise TaxonomyError(
                f"Persona '{persona.id}' uses unknown topic id(s): {', '.join(unknown)}"
            )
    return personas


def load_taxonomy(topics_path: Path, personas_path: Path) -> Taxonomy:
    """Load both files and check that they agree with each other."""
    topics = load_topics(topics_path)
    return Taxonomy(topics=topics, personas=load_personas(personas_path, topics))
