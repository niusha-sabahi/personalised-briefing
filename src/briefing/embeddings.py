"""Embed sources and topic descriptions with OpenAI, with an on-disk cache."""

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from openai import OpenAI

from briefing.models import PreparedSource, Topic

# Embedding models accept about 8k tokens. Scraped text runs at roughly 3 to 4 characters
# per token, so this stays under the limit with margin and still covers a median page.
MAX_EMBED_CHARS = 16_000
# A request is capped in total tokens, so batches stay small enough for long pages.
BATCH_SIZE = 16


class Embedder(Protocol):
    """Anything that turns texts into vectors. Tests replace the OpenAI one with a fake."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one vector per text, in the same order."""
        ...


def source_embedding_text(item: PreparedSource) -> str:
    """Return the text embedded for a source: its title, then its cleaned text, truncated."""
    return f"{item.source.title}\n\n{item.clean_text}"[:MAX_EMBED_CHARS]


def topic_embedding_text(topic: Topic) -> str:
    """Return the text embedded for a topic: its description."""
    return topic.description


class OpenAIEmbedder:
    """Embedder backed by the OpenAI embeddings API."""

    def __init__(self, client: OpenAI, model: str, batch_size: int = BATCH_SIZE) -> None:
        """Create an embedder that calls `model` through `client`, `batch_size` texts at a time."""
        self._client = client
        self._model = model
        self._batch_size = batch_size

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed `texts` in fixed-size batches, keeping the input order."""
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = list(texts[start : start + self._batch_size])
            response = self._client.embeddings.create(model=self._model, input=batch)
            # The API tags each result with its input index; sort rather than assume order.
            vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
        return vectors


class EmbeddingCache:
    """Vectors on disk, one JSON file per text, keyed by a hash of the model and the text."""

    def __init__(self, directory: Path, model: str) -> None:
        """Store vectors for `model` under `directory`."""
        self._directory = directory
        self._model = model

    def _path(self, text: str) -> Path:
        # Hashing the content means an edited source or topic description misses the cache
        # (and is re-embedded) while everything unchanged is reused. The model is part of
        # the key so switching models never serves vectors from the old one.
        digest = hashlib.sha256(f"{self._model}\n{text}".encode()).hexdigest()
        return self._directory / f"{digest}.json"

    def get(self, text: str) -> list[float] | None:
        """Return the cached vector for `text`, or None if absent or unreadable."""
        try:
            data = json.loads(self._path(text).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, list) or not all(isinstance(x, float | int) for x in data):
            return None
        return [float(x) for x in data]

    def put(self, text: str, vector: Sequence[float]) -> None:
        """Store the vector for `text`."""
        path = self._path(text)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write then rename so an interrupted run never leaves a half-written file behind.
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(list(vector)), encoding="utf-8")
        temp.replace(path)


class CachedEmbedder:
    """Embedder that serves repeat texts from the cache and sends only new ones on."""

    def __init__(self, inner: Embedder, cache: EmbeddingCache) -> None:
        """Wrap `inner` with `cache`. `hits` and `misses` count texts served and embedded."""
        self._inner = inner
        self._cache = cache
        self.hits = 0
        self.misses = 0

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one vector per text, calling the inner embedder only for uncached texts."""
        found: dict[str, list[float]] = {}
        missing: list[str] = []
        for text in dict.fromkeys(texts):
            cached = self._cache.get(text)
            if cached is None:
                missing.append(text)
            else:
                found[text] = cached
        self.hits += len(found)
        self.misses += len(missing)
        if missing:
            for text, vector in zip(missing, self._inner.embed(missing), strict=True):
                self._cache.put(text, vector)
                found[text] = vector
        return [found[text] for text in texts]
