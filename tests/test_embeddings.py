from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from briefing.embeddings import (
    MAX_EMBED_CHARS,
    CachedEmbedder,
    EmbeddingCache,
    OpenAIEmbedder,
    source_embedding_text,
    topic_embedding_text,
)
from briefing.models import PreparedSource, Source, Topic


class FakeEmbedder:
    """Returns a vector derived from the text and records every call."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(len(text)), 1.0] for text in texts]


class FakeOpenAIClient:
    """Mimics `client.embeddings.create`, returning results out of order on purpose."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.embeddings = SimpleNamespace(create=self._create)

    def _create(self, model: str, input: list[str]) -> SimpleNamespace:  # noqa: A002
        self.requests.append({"model": model, "input": input})
        data = [SimpleNamespace(index=i, embedding=[float(len(t))]) for i, t in enumerate(input)]
        return SimpleNamespace(data=list(reversed(data)))


def prepared(title: str, text: str) -> PreparedSource:
    source = Source(id="1", url="https://x.test/a", title=title, description="", text=text)
    return PreparedSource(source=source, clean_text=text, published=None)


# --- texts -------------------------------------------------------------------------


def test_source_text_starts_with_title_and_is_truncated() -> None:
    text = source_embedding_text(prepared("My title", "word " * 10_000))
    assert text.startswith("My title\n\nword")
    assert len(text) == MAX_EMBED_CHARS


def test_short_source_text_is_not_padded() -> None:
    assert source_embedding_text(prepared("T", "body")) == "T\n\nbody"


def test_topic_text_is_its_description() -> None:
    topic = Topic(id="a", label="A", description="A description long enough to be valid.")
    assert topic_embedding_text(topic) == topic.description


# --- OpenAI embedder -----------------------------------------------------------------


def test_openai_embedder_batches_and_keeps_input_order() -> None:
    client = FakeOpenAIClient()
    embedder = OpenAIEmbedder(client, "embed-model", batch_size=2)  # type: ignore[arg-type]
    vectors = embedder.embed(["a", "bb", "ccc", "dddd", "eeeee"])
    assert vectors == [[1.0], [2.0], [3.0], [4.0], [5.0]]
    assert [r["input"] for r in client.requests] == [["a", "bb"], ["ccc", "dddd"], ["eeeee"]]
    assert {r["model"] for r in client.requests} == {"embed-model"}


def test_openai_embedder_makes_no_request_for_no_texts() -> None:
    client = FakeOpenAIClient()
    assert OpenAIEmbedder(client, "m").embed([]) == []  # type: ignore[arg-type]
    assert client.requests == []


# --- cache ---------------------------------------------------------------------------


def test_cache_round_trip(tmp_path: Path) -> None:
    cache = EmbeddingCache(tmp_path / "nested", "m")
    assert cache.get("text") is None
    cache.put("text", [0.5, -1.0])
    assert cache.get("text") == [0.5, -1.0]


def test_cache_is_keyed_by_model_and_content(tmp_path: Path) -> None:
    EmbeddingCache(tmp_path, "model-a").put("text", [1.0])
    assert EmbeddingCache(tmp_path, "model-b").get("text") is None
    assert EmbeddingCache(tmp_path, "model-a").get("other text") is None
    assert EmbeddingCache(tmp_path, "model-a").get("text") == [1.0]


def test_cache_ignores_corrupt_files(tmp_path: Path) -> None:
    cache = EmbeddingCache(tmp_path, "m")
    cache.put("text", [1.0])
    (next(tmp_path.glob("*.json"))).write_text("{not json", encoding="utf-8")
    assert cache.get("text") is None
    (next(tmp_path.glob("*.json"))).write_text('{"a": 1}', encoding="utf-8")
    assert cache.get("text") is None


def test_cache_leaves_no_temp_files(tmp_path: Path) -> None:
    EmbeddingCache(tmp_path, "m").put("text", [1.0])
    assert [p.suffix for p in tmp_path.iterdir()] == [".json"]


# --- cached embedder -----------------------------------------------------------------


def test_repeat_run_makes_no_inner_calls(tmp_path: Path) -> None:
    inner = FakeEmbedder()
    first = CachedEmbedder(inner, EmbeddingCache(tmp_path, "m"))
    expected = first.embed(["a", "bb"])
    assert (first.hits, first.misses) == (0, 2)

    second = CachedEmbedder(inner, EmbeddingCache(tmp_path, "m"))
    assert second.embed(["a", "bb"]) == expected
    assert (second.hits, second.misses) == (2, 0)
    assert len(inner.calls) == 1


def test_only_new_texts_are_embedded_and_order_is_kept(tmp_path: Path) -> None:
    inner = FakeEmbedder()
    embedder = CachedEmbedder(inner, EmbeddingCache(tmp_path, "m"))
    embedder.embed(["old"])
    vectors = embedder.embed(["new", "old", "newer"])
    assert inner.calls[-1] == ["new", "newer"]
    assert [v[0] for v in vectors] == [3.0, 3.0, 5.0]


def test_duplicate_texts_in_one_call_are_embedded_once(tmp_path: Path) -> None:
    inner = FakeEmbedder()
    embedder = CachedEmbedder(inner, EmbeddingCache(tmp_path, "m"))
    assert len(embedder.embed(["a", "a", "a"])) == 3
    assert inner.calls == [["a"]]
