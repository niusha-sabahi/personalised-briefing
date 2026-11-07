from collections.abc import Callable
from pathlib import Path

import pytest

from briefing.main import run
from briefing.topics import (
    TaxonomyError,
    load_personas,
    load_taxonomy,
    load_topics,
)

ROOT = Path(__file__).resolve().parent.parent
REAL_TOPICS = ROOT / "topics.yaml"
REAL_PERSONAS = ROOT / "personas.yaml"

DESCRIPTION = "A description that is comfortably long enough to be valid."

# The interests listed for the two personas in task.md (M3.1).
REQUIRED_TOPIC_IDS = {
    "healthcare-reform",
    "public-health-data",
    "telemedicine",
    "pharmaceutical-innovation",
    "health-equity",
    "government-policy-updates",
    "artificial-intelligence",
    "venture-capital",
    "startup-funding",
    "saas-trends",
    "product-management",
}


def topic_yaml(*ids: str) -> str:
    items = "".join(
        f"  - id: {i}\n    label: Label {i}\n    description: {DESCRIPTION}\n" for i in ids
    )
    return f"topics:\n{items}"


def persona_yaml(*personas: tuple[str, tuple[str, ...]]) -> str:
    items = ""
    for persona_id, topic_ids in personas:
        topics = "".join(f"      - {t}\n" for t in topic_ids)
        items += (
            f"  - id: {persona_id}\n    position: Analyst\n    location: Nowhere\n"
            f"    topic_ids:\n{topics}"
        )
    return f"personas:\n{items}"


WriteFile = Callable[[str, str], Path]


@pytest.fixture
def write(tmp_path: Path) -> WriteFile:
    def _write(name: str, content: str) -> Path:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        return path

    return _write


# --- topics ------------------------------------------------------------------------


def test_load_valid_topics(write: WriteFile) -> None:
    topics = load_topics(write("t.yaml", topic_yaml("alpha", "beta-two")))
    assert [t.id for t in topics] == ["alpha", "beta-two"]
    assert topics[0].description == DESCRIPTION


def test_duplicate_topic_ids_are_rejected(write: WriteFile) -> None:
    with pytest.raises(TaxonomyError, match="Duplicate topic id.*alpha"):
        load_topics(write("t.yaml", topic_yaml("alpha", "beta", "alpha")))


@pytest.mark.parametrize("bad_id", ["Alpha", "has space", "under_score", "-lead", "trail-", ""])
def test_topic_ids_must_be_lowercase_slugs(write: WriteFile, bad_id: str) -> None:
    with pytest.raises(TaxonomyError, match="Invalid topic"):
        load_topics(write("t.yaml", topic_yaml(f'"{bad_id}"')))


def test_topic_needs_a_real_description(write: WriteFile) -> None:
    content = "topics:\n  - id: alpha\n    label: Alpha\n    description: short\n"
    with pytest.raises(TaxonomyError, match="Invalid topic"):
        load_topics(write("t.yaml", content))


def test_unknown_topic_fields_are_rejected(write: WriteFile) -> None:
    content = topic_yaml("alpha") + "    descripton: typo\n"
    with pytest.raises(TaxonomyError, match="Invalid topic"):
        load_topics(write("t.yaml", content))


@pytest.mark.parametrize("content", ["", "just text", "topics: []", "other: [1]", "topics: {a: 1}"])
def test_topics_file_must_have_a_non_empty_list(write: WriteFile, content: str) -> None:
    with pytest.raises(TaxonomyError, match="non-empty list under 'topics'"):
        load_topics(write("t.yaml", content))


def test_malformed_yaml_and_missing_file(write: WriteFile, tmp_path: Path) -> None:
    with pytest.raises(TaxonomyError, match="Cannot read"):
        load_topics(write("t.yaml", "topics: [unclosed"))
    with pytest.raises(TaxonomyError, match="Cannot read"):
        load_topics(tmp_path / "missing.yaml")


# --- personas ----------------------------------------------------------------------


def test_load_valid_personas(write: WriteFile) -> None:
    topics = load_topics(write("t.yaml", topic_yaml("alpha", "beta")))
    personas = load_personas(write("p.yaml", persona_yaml(("one", ("alpha", "beta")))), topics)
    assert personas[0].topic_ids == ("alpha", "beta")
    assert (personas[0].position, personas[0].location) == ("Analyst", "Nowhere")


def test_unknown_topic_id_in_persona_is_rejected(write: WriteFile) -> None:
    topics = load_topics(write("t.yaml", topic_yaml("alpha")))
    content = persona_yaml(("one", ("alpha", "ghost")))
    with pytest.raises(TaxonomyError, match="'one' uses unknown topic id.*ghost"):
        load_personas(write("p.yaml", content), topics)


def test_duplicate_persona_ids_are_rejected(write: WriteFile) -> None:
    topics = load_topics(write("t.yaml", topic_yaml("alpha")))
    content = persona_yaml(("one", ("alpha",)), ("one", ("alpha",)))
    with pytest.raises(TaxonomyError, match="Duplicate persona id.*one"):
        load_personas(write("p.yaml", content), topics)


def test_persona_cannot_repeat_a_topic(write: WriteFile) -> None:
    topics = load_topics(write("t.yaml", topic_yaml("alpha")))
    content = persona_yaml(("one", ("alpha", "alpha")))
    with pytest.raises(TaxonomyError, match="repeats topic id.*alpha"):
        load_personas(write("p.yaml", content), topics)


def test_persona_needs_at_least_one_topic(write: WriteFile) -> None:
    topics = load_topics(write("t.yaml", topic_yaml("alpha")))
    content = "personas:\n  - id: one\n    position: P\n    location: L\n    topic_ids: []\n"
    with pytest.raises(TaxonomyError, match="Invalid persona"):
        load_personas(write("p.yaml", content), topics)


def test_taxonomy_lookup(write: WriteFile) -> None:
    taxonomy = load_taxonomy(
        write("t.yaml", topic_yaml("alpha")), write("p.yaml", persona_yaml(("one", ("alpha",))))
    )
    assert taxonomy.topic("alpha") is not None and taxonomy.topic("nope") is None
    assert taxonomy.persona("one") is not None and taxonomy.persona("nope") is None


# --- the real files (S18) ------------------------------------------------------------


def test_real_files_are_valid_and_include_the_required_topics() -> None:
    taxonomy = load_taxonomy(REAL_TOPICS, REAL_PERSONAS)
    assert {t.id for t in taxonomy.topics} >= REQUIRED_TOPIC_IDS


def test_real_personas_follow_the_task() -> None:
    taxonomy = load_taxonomy(REAL_TOPICS, REAL_PERSONAS)
    health = taxonomy.persona("healthcare-policy-analyst")
    founder = taxonomy.persona("tech-founder")
    assert health is not None and founder is not None
    assert set(health.topic_ids) == {
        "healthcare-reform",
        "public-health-data",
        "telemedicine",
        "pharmaceutical-innovation",
        "health-equity",
        "government-policy-updates",
    }
    assert set(founder.topic_ids) == {
        "artificial-intelligence",
        "venture-capital",
        "startup-funding",
        "saas-trends",
        "product-management",
    }
    assert "United States" in health.location and "London" in founder.location


def test_real_topics_never_mention_a_persona() -> None:
    # M3: embeddings and tags are about topics only, so a persona's words must not leak in.
    taxonomy = load_taxonomy(REAL_TOPICS, REAL_PERSONAS)
    words = {"persona", "analyst", "founder", "london"}
    for topic in taxonomy.topics:
        text = f"{topic.label} {topic.description}".lower()
        assert not any(word in text for word in words), topic.id


def test_every_real_topic_is_used_by_a_persona() -> None:
    taxonomy = load_taxonomy(REAL_TOPICS, REAL_PERSONAS)
    used = {t for p in taxonomy.personas for t in p.topic_ids}
    assert {t.id for t in taxonomy.topics} == used


# --- the `topics` command ------------------------------------------------------------


def test_topics_command_reports_valid_files(capsys: pytest.CaptureFixture[str]) -> None:
    run(["topics", "--topics", str(REAL_TOPICS), "--personas", str(REAL_PERSONAS)])
    out = capsys.readouterr().out
    assert "11 topics, 2 personas: files are valid." in out
    assert "tech-founder (Tech Startup Founder, London, United Kingdom)" in out
    assert "Topics no persona uses" not in out


def test_topics_command_exits_with_an_error_for_invalid_files(
    write: WriteFile,
    capsys: pytest.CaptureFixture[str],
) -> None:
    topics = write("t.yaml", topic_yaml("alpha"))
    personas = write("p.yaml", persona_yaml(("one", ("ghost",))))
    with pytest.raises(SystemExit) as exit_info:
        run(["topics", "--topics", str(topics), "--personas", str(personas)])
    assert exit_info.value.code == 1
    assert "unknown topic id" in capsys.readouterr().err


def test_topics_command_lists_unused_topics(
    write: WriteFile,
    capsys: pytest.CaptureFixture[str],
) -> None:
    topics = write("t.yaml", topic_yaml("alpha", "beta"))
    personas = write("p.yaml", persona_yaml(("one", ("alpha",))))
    run(["topics", "--topics", str(topics), "--personas", str(personas)])
    assert "Topics no persona uses: beta" in capsys.readouterr().out
