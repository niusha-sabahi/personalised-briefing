"""Builds briefings for personas on demand and keeps them in memory (S11)."""

import logging
import threading

import openai

from briefing.config import Settings
from briefing.embeddings import (
    CachedEmbedder,
    Embedder,
    EmbeddingCache,
    OpenAIEmbedder,
)
from briefing.generation import Generator, OpenAIGenerator, generate_briefing
from briefing.models import Briefing, Persona, PreparedSource
from briefing.retrieval import TaggedSource, build_context, select_sources, tag_corpus
from briefing.sources import load_sources, prepare_sources, select_usable
from briefing.topics import Taxonomy

logger = logging.getLogger(__name__)


def make_openai_client(settings: Settings) -> openai.OpenAI:
    """Create the OpenAI client with the configured timeout and retry count."""
    return openai.OpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        timeout=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
    )


def make_embedder(settings: Settings) -> CachedEmbedder:
    """Create the disk-cached OpenAI embedder described by `settings`."""
    inner = OpenAIEmbedder(make_openai_client(settings), settings.embedding_model)
    return CachedEmbedder(inner, EmbeddingCache(settings.cache_path, settings.embedding_model))


class BriefingService:
    """Selects sources, retrieves passages and generates a briefing for a persona.

    Embedding the sources is the expensive step, so it happens on the first briefing request
    (not at startup, so `/health` and `/topics` work without calling OpenAI) and the tags are
    kept. Finished briefings are cached per persona until the process restarts. Failures are
    never cached.
    """

    def __init__(
        self,
        settings: Settings,
        taxonomy: Taxonomy,
        usable_sources: list[PreparedSource],
        embedder: Embedder,
        generator: Generator,
    ) -> None:
        """Create a service over already-loaded data and the given model clients."""
        self._settings = settings
        self._taxonomy = taxonomy
        self._usable = usable_sources
        self._embedder = embedder
        self._generator = generator
        self._tagged: list[TaggedSource] | None = None
        self._briefings: dict[str, Briefing] = {}
        # Requests run in worker threads; one lock keeps two first requests from embedding
        # and generating the same thing twice.
        self._lock = threading.Lock()

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        taxonomy: Taxonomy,
        embedder: Embedder | None = None,
        generator: Generator | None = None,
    ) -> "BriefingService":
        """Load and clean the sources, and create OpenAI clients unless fakes are given."""
        prepared = prepare_sources(load_sources(settings.sources_path), settings.latest_date)
        usable = select_usable(prepared, settings.cutoff_date)
        logger.info(
            "Loaded %d sources, %d usable (published on or after %s)",
            len(prepared),
            len(usable),
            settings.cutoff_date,
        )
        if embedder is None:
            embedder = make_embedder(settings)
        if generator is None:
            generator = OpenAIGenerator(make_openai_client(settings), settings.generation_model)
        return cls(settings, taxonomy, usable, embedder, generator)

    def briefing_for(self, persona: Persona) -> Briefing:
        """Return the persona's briefing, generating it on the first request.

        Raises:
            NoRelevantSourcesError: If no recent, tagged source has a relevant passage.
            GenerationError: If the model's answer was unusable.
            openai.OpenAIError: If an OpenAI request failed.
        """
        with self._lock:
            cached = self._briefings.get(persona.id)
            if cached is not None:
                logger.info("Briefing for %s served from memory", persona.id)
                return cached
            briefing = self._generate(persona)
            self._briefings[persona.id] = briefing
            return briefing

    def _generate(self, persona: Persona) -> Briefing:
        settings = self._settings
        if self._tagged is None:
            self._tagged = tag_corpus(
                self._usable,
                self._taxonomy.topics,
                self._embedder,
                settings.tagging_threshold,
                settings.max_tags_per_source,
            )
            logger.info(
                "Tagged %d sources, %d with at least one topic",
                len(self._tagged),
                sum(1 for item in self._tagged if item.tags),
            )
        selected = select_sources(
            self._tagged, persona.topic_ids, settings.top_k, settings.per_topic_min
        )
        topics = [self._taxonomy.topic(topic_id) for topic_id in persona.topic_ids]
        persona_topics = [topic for topic in topics if topic is not None]
        context = build_context(
            selected,
            persona_topics,
            self._embedder,
            settings.passage_threshold,
            settings.max_passages_per_topic,
            settings.max_passages_per_source,
            settings.max_passages_per_source_per_topic,
            (settings.cutoff_date, settings.latest_date),
            settings.recency_bonus,
        )
        logger.info(
            "Persona %s: %d sources selected, %d kept with %d passages",
            persona.id,
            len(selected),
            len(context.sources),
            len(context.passages),
        )
        briefing = generate_briefing(persona, persona_topics, context, self._generator)
        logger.info(
            "Briefing for %s generated: %d sources cited, %d bullets and %d citations dropped",
            persona.id,
            len(briefing.sources),
            briefing.dropped_bullets,
            briefing.dropped_citations,
        )
        return briefing
