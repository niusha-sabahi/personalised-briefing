"""FastAPI application: health, taxonomy and persona briefings."""

import logging
import mimetypes
import re
import traceback
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Literal

import openai
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from briefing.config import Settings
from briefing.embeddings import Embedder
from briefing.generation import GenerationError, Generator, NoRelevantSourcesError
from briefing.models import Briefing, Persona, Topic
from briefing.service import BriefingService
from briefing.topics import load_taxonomy

logger = logging.getLogger(__name__)

MARKDOWN_TYPE = "text/markdown; charset=utf-8"
STATIC_DIR = Path(__file__).parent / "static"

# Sent with the page and its assets (S8). The page needs nothing but its own scripts, styles
# and API, so everything else is refused: injected markup could not run script or load
# resources even if sanitising failed. `/docs` is left alone because it loads its own assets.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    # Browsers may reuse a stylesheet or icon for a long time without asking. This makes them
    # check each time (a cheap 304 when nothing changed), so a style change shows on reload.
    "Cache-Control": "no-cache",
}

# Windows can map .js to text/plain through the registry, and with `nosniff` the browser
# would then refuse to run the scripts.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")


class HealthResponse(BaseModel):
    """Body returned by the health check."""

    status: str


class ErrorResponse(BaseModel):
    """Body of every error response. It never contains provider messages or stack traces."""

    detail: str


def configure_logging(level: str) -> None:
    """Send the application's logs to the console at `level` (S15)."""
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("briefing").setLevel(level)


_KEY_LIKE = re.compile(r"\b(?:sk|pk|rk)-[^\s'\",)]+|Bearer\s+\S+", re.IGNORECASE)


def mask_secrets(text: str, secrets: Sequence[str] = ()) -> str:
    """Hide the configured secrets, and anything shaped like a key or bearer token, in `text`.

    The configured values are replaced exactly, so the key is hidden even if it does not look
    like a key; the pattern catches any other key a provider message might echo.
    """
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[masked]")
    return _KEY_LIKE.sub("[masked]", text)


def _error_handler(
    status: int, message: str, secrets: Sequence[str]
) -> Callable[[Request, Exception], JSONResponse]:
    def handle(request: Request, exc: Exception) -> JSONResponse:
        # At INFO and above only the exception class and HTTP status are logged for provider
        # errors: their messages can echo fragments of the API key.
        provider_status = getattr(exc, "status_code", None)
        log = logger.warning if status < 500 else logger.error
        log(
            "%s on %s -> %d (provider status %s)",
            type(exc).__name__,
            request.url.path,
            status,
            provider_status,
        )
        # The provider's own message is what says which request parameter it rejected, so it
        # is available when debugging, with key-like text masked. It is never in a response.
        logger.debug("Detail with secrets masked: %s", mask_secrets(str(exc), secrets))
        return JSONResponse(status_code=status, content={"detail": message})

    return handle


def _unexpected_error_handler(
    secrets: Sequence[str],
) -> Callable[[Request, Exception], JSONResponse]:
    def handle(request: Request, exc: Exception) -> JSONResponse:
        # The traceback is logged as text, with secrets masked, because the exception message
        # at its end could contain one.
        trace = "".join(traceback.format_exception(exc))
        logger.error("Unexpected error on %s\n%s", request.url.path, mask_secrets(trace, secrets))
        return JSONResponse(status_code=500, content={"detail": "Internal server error."})

    return handle


# Most specific first is not required: Starlette picks the handler for the closest class.
_ERROR_MAP: tuple[tuple[type[Exception], int, str], ...] = (
    (NoRelevantSourcesError, 404, "No relevant recent sources were found for this persona."),
    (GenerationError, 502, "The AI model did not return a usable briefing. Try again."),
    (openai.RateLimitError, 503, "The AI provider is rate limiting requests. Try again shortly."),
    (openai.APIConnectionError, 503, "The AI provider could not be reached. Try again shortly."),
    (openai.AuthenticationError, 502, "The AI provider rejected this service's credentials."),
    (openai.PermissionDeniedError, 502, "The AI provider denied access for this service."),
    (openai.OpenAIError, 502, "The AI provider returned an error."),
)


def create_app(
    settings: Settings | None = None,
    *,
    embedder: Embedder | None = None,
    generator: Generator | None = None,
) -> FastAPI:
    """Build the application, validating the topic and persona files and loading the sources.

    Args:
        settings: Configuration; read from the environment when omitted.
        embedder: Replacement for the OpenAI embedder (tests).
        generator: Replacement for the OpenAI generator (tests).

    Raises:
        TaxonomyError: If `topics.yaml` or `personas.yaml` is invalid (S9).
        SourceDataError: If the sources file cannot be read.
    """
    settings = settings or Settings()
    configure_logging(settings.log_level)
    taxonomy = load_taxonomy(settings.topics_path, settings.personas_path)
    service = BriefingService.from_settings(settings, taxonomy, embedder, generator)

    secrets = (settings.openai_api_key.get_secret_value(),)
    app = FastAPI(title="Executive Briefing", version="0.1.0")
    for exc_class, status, message in _ERROR_MAP:
        app.add_exception_handler(exc_class, _error_handler(status, message, secrets))
    app.add_exception_handler(Exception, _unexpected_error_handler(secrets))

    @app.middleware("http")
    async def add_security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers.update(SECURITY_HEADERS)
        return response

    @app.get("/", include_in_schema=False)
    def frontend() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html; charset=utf-8")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/health", response_model=HealthResponse, summary="Liveness check")
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/topics", response_model=list[Topic], summary="The topic taxonomy")
    def topics() -> list[Topic]:
        return list(taxonomy.topics)

    @app.get("/personas", response_model=list[Persona], summary="The available personas")
    def personas() -> list[Persona]:
        return list(taxonomy.personas)

    @app.get(
        "/briefings/{persona_id}",
        response_model=None,
        summary="A persona's briefing",
        description=(
            "Returns the briefing as Markdown (`text/markdown`), or as JSON with the cited "
            "sources when `format=json`. The first request for a persona calls OpenAI and can "
            "take a while; later requests are served from memory."
        ),
        responses={
            200: {
                "description": "The briefing.",
                "content": {
                    "text/markdown": {"schema": {"type": "string"}},
                    "application/json": {"schema": Briefing.model_json_schema()},
                },
            },
            404: {
                "model": ErrorResponse,
                "description": "Unknown persona, or no relevant recent sources for it.",
            },
            502: {"model": ErrorResponse, "description": "The AI provider failed or refused."},
            503: {
                "model": ErrorResponse,
                "description": "The AI provider is rate limiting or unreachable.",
            },
        },
    )
    def briefing(persona_id: str, format: Literal["markdown", "json"] = "markdown") -> Response:
        persona = taxonomy.persona(persona_id)
        if persona is None:
            known = ", ".join(p.id for p in taxonomy.personas)
            raise HTTPException(
                status_code=404, detail=f"Unknown persona. Known personas: {known}."
            )
        result = service.briefing_for(persona)
        if format == "json":
            # JSON mode makes dates and times ISO strings; plain `model_dump` leaves objects.
            return JSONResponse(result.model_dump(mode="json"))
        return Response(content=result.markdown, media_type=MARKDOWN_TYPE)

    return app
