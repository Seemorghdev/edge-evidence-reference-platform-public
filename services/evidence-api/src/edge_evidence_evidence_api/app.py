"""Evidence API exposing public-safe synthetic projections."""

from __future__ import annotations

import os
from typing import Annotated

import uvicorn
from edge_evidence_contracts.models import ArtifactProjection, EvidenceReceipt
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .store import store

app = FastAPI(
    title="Edge Evidence API",
    version="0.2.0",
    description=(
        "Read-oriented API for synthetic reference-platform projections. "
        "It is not an evidence authority and does not execute workers."
    ),
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


@app.get("/healthz", tags=["platform"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["platform"])
def readyz() -> dict[str, str]:
    return {"status": "ready", "authority": "synthetic-only"}


@app.get("/api/v1/artifacts", response_model=list[ArtifactProjection], tags=["evidence"])
def list_artifacts(
    state: Annotated[str | None, Query(description="Optional artifact state filter")] = None,
) -> list[ArtifactProjection]:
    artifacts = store.list_artifacts()
    return [artifact for artifact in artifacts if state is None or artifact.state.value == state]


@app.get("/api/v1/artifacts/{artifact_id}", response_model=ArtifactProjection, tags=["evidence"])
def get_artifact(artifact_id: str) -> ArtifactProjection:
    artifact = store.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    return artifact


@app.get("/api/v1/receipts", response_model=list[EvidenceReceipt], tags=["evidence"])
def list_receipts() -> list[EvidenceReceipt]:
    return store.list_receipts()


@app.get("/api/v1/receipts/{receipt_id}", response_model=EvidenceReceipt, tags=["evidence"])
def get_receipt(receipt_id: str) -> EvidenceReceipt:
    receipt = store.get_receipt(receipt_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="receipt not found")
    return receipt


@app.post("/api/v1/demo/reset", tags=["demo"])
def reset_demo() -> dict[str, int | str]:
    store.reset()
    return {
        "status": "reset",
        "artifacts": len(store.list_artifacts()),
        "receipts": len(store.list_receipts()),
    }


def main() -> None:
    uvicorn.run(
        "edge_evidence_evidence_api.app:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8080")),
    )


if __name__ == "__main__":
    main()
