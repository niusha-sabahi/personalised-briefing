"""Command-line entry point that starts the API server."""

import uvicorn


def run() -> None:
    """Serve the API on localhost:8000 (the `briefing` script)."""
    uvicorn.run("briefing.api:app", host="127.0.0.1", port=8000)
