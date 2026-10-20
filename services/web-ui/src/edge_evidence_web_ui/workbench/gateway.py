"""Read-only hosted Gateway, never a local-model supervisor.

Actual runtime imports existing public service apps, retaining their source
routes. Missing native service imports fail closed.
No local model, worker, background refresh or provider network call exists.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from edge_evidence_edge_agent.app import app as agent_service
from edge_evidence_evidence_api.app import app as evidence_service
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
TEST_FIXTURES = False

app = FastAPI(title="Edge Evidence — read-only Gateway", version="0.3.0")


def routes_from(source: FastAPI, allowed: set[str]):
    router = APIRouter()
    for route in source.router.routes:
        if isinstance(route, APIRoute) and route.path in allowed:
            router.routes.append(route)
    return router


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index():
    return HTMLResponse(
        (ROOT / "index.html").read_text(encoding="utf8"),
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "object-src 'none'; base-uri 'none'; form-action 'none'; connect-src 'self'"
            ),
        },
    )


@app.get("/api/review/capabilities")
def capabilities():
    return {
        "mode": "hosted",
        "inspect": "deterministic-read-only",
        "proof": "retained-synthetic",
        "llama": "local-only-unavailable-here",
        "test_fixture_services": TEST_FIXTURES,
    }


PROOF_PATH = ROOT / "retained-proof.json"
PROVENANCE_PATH = ROOT / "retained-provenance.json"


@app.get("/api/review/proof")
def retained_proof():
    # Exact retained bytes and retrieval metadata, no live remote/proxy call.
    try:
        raw = PROOF_PATH.read_bytes()
        provenance = json.loads(PROVENANCE_PATH.read_text())
        digest = hashlib.sha256(raw).hexdigest()
        if digest != provenance.get("snapshot_sha256"):
            raise ValueError("snapshot digest mismatch")
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("mode") != "synthetic-stateless":
            raise ValueError("wrong retained proof type")
        if provenance.get("execution_time_utc") is not None:
            raise ValueError("unexpected original execution date claim")
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(
            status_code=503, detail="Retained proof unavailable or unverified"
        ) from None
    return {
        "snapshot": data,
        "provenance": provenance,
        "verification": {
            "bytes_sha256_checked": True,
            "source_bytes": data.get("summary", {})
            .get("handoff", {})
            .get("source", {})
            .get("byte_size"),
            "target_bytes": data.get("summary", {})
            .get("handoff", {})
            .get("replication", {})
            .get("target_byte_size"),
        },
    }


app.include_router(
    routes_from(
        evidence_service,
        {
            "/readyz",
            "/api/v1/artifacts",
            "/api/v1/artifacts/{artifact_id}",
            "/api/v1/receipts",
            "/api/v1/receipts/{receipt_id}",
        },
    )
)
app.include_router(routes_from(agent_service, {"/health", "/api/v1/inspect"}))
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
