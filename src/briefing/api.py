"""FastAPI application and routes."""

from fastapi import FastAPI
from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Body returned by the health check."""

    status: str


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    app = FastAPI(title="Personalised Briefing", version="0.1.0")

    @app.get("/health", response_model=HealthResponse, summary="Liveness check")
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    return app


app = create_app()
