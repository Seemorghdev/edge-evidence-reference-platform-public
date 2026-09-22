"""Bounded Edge Agent HTTP surface."""

from __future__ import annotations

import os

import uvicorn
from edge_evidence_contracts.models import AgentInspection, ArtifactProjection
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core import inspect_artifact

app = FastAPI(
    title="Bounded Edge Agent",
    version="0.2.0",
    description="Read-only deterministic inspection with an optional default-off ADK adapter.",
)

allowed_origins = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:8082").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["content-type"],
)


def _health_response() -> dict[str, str | bool]:
    return {"status": "ok", "mutation_authorized": False}


@app.get("/health", tags=["platform"])
def health() -> dict[str, str | bool]:
    """Cloud Run-safe external health route."""
    return _health_response()


@app.get("/healthz", tags=["platform"])
def healthz() -> dict[str, str | bool]:
    """Compatibility route for local and internal health checks."""
    return _health_response()


@app.post("/api/v1/inspect", response_model=AgentInspection, tags=["agent"])
def inspect(payload: ArtifactProjection) -> AgentInspection:
    return inspect_artifact(payload)


def main() -> None:
    uvicorn.run(
        "edge_evidence_edge_agent.app:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8081")),
    )


if __name__ == "__main__":
    main()
