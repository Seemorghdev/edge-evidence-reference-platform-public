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
from fastapi.responses import HTMLResponse, Response
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


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


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

# Playback of the retained snapshot. "recorded" entries are JSON paths into the
# snapshot and are only ever quoted; "presentation" is wording added by this
# page. Nothing here runs a worker, reads a target or calls a model.
PLAYBACK_STEPS = (
    {
        "id": "processor",
        "title": "Processor",
        "presentation": (
            "The Processor's derived report as recorded in the snapshot. "
            "This page does not run the Processor."
        ),
        "recorded": (
            "summary.components.processor.status",
            "summary.components.processor.proof_class",
            "summary.components.processor.output_sha256",
            "summary.handoff.source.byte_size",
        ),
    },
    {
        "id": "handoff",
        "title": "Handoff",
        "presentation": (
            "The same identity is recorded as the Replication source and as the "
            "object the replication authority expected."
        ),
        "recorded": (
            "summary.handoff.source.sha256",
            "summary.handoff.replication.authority.expected_sha256",
            "summary.handoff.replication.authority.expected_byte_size",
            "summary.handoff.invariants.processor_output_was_replication_source",
        ),
    },
    {
        "id": "replication",
        "title": "Replication",
        "presentation": (
            "The first recorded Replication run. The counts are as recorded; "
            "this page does not write to any target."
        ),
        "recorded": (
            "summary.handoff.replication.first_run.discovered",
            "summary.handoff.replication.first_run.inserted",
            "summary.handoff.replication.first_run.published",
            "summary.handoff.replication.first_run.adopted",
            "summary.handoff.replication.first_run.verified",
            "summary.handoff.invariants.immutable_create_performed",
        ),
    },
    {
        "id": "readback",
        "title": "Readback",
        "presentation": (
            "A separate recorded verification pass read the target back. These "
            "target values were recorded at that time; this page reads no target."
        ),
        "recorded": (
            "summary.handoff.replication.verification.verified",
            "summary.handoff.replication.verification.published",
            "summary.handoff.replication.target_byte_size",
            "summary.handoff.replication.target_sha256",
            "summary.handoff.replication.authority.state",
            "summary.handoff.replication.authority.attempt_count",
            "summary.handoff.replication.authority.last_error",
            "summary.handoff.invariants.independent_readback_verified",
            "summary.handoff.invariants.target_bytes_match_processor_output",
        ),
    },
    {
        "id": "replay",
        "title": "Replay",
        "presentation": "The recorded exact rerun of the same Replication work.",
        "recorded": (
            "summary.handoff.replication.replay.discovered",
            "summary.handoff.replication.replay.inserted",
            "summary.handoff.replication.replay.published",
            "summary.handoff.replication.replay.adopted",
            "summary.handoff.replication.replay.verified",
            "summary.handoff.invariants.exact_replay_is_noop",
        ),
    },
)

PLAYBACK_AGGREGATE = {
    "id": "standalone",
    "title": "Standalone worker proofs",
    "presentation": (
        "The snapshot records these standalone proofs only as passed, with the "
        "hash of a summary file that is not part of this snapshot. Their "
        "individual scenarios are not shown because this snapshot does not "
        "contain them."
    ),
    "recorded": (
        "summary.invariants.processor_reliability_proofs_passed",
        "summary.components.processor.summary_path",
        "summary.components.processor.summary_sha256",
        "summary.invariants.replication_standalone_proofs_passed",
        "summary.components.replication.summary_path",
        "summary.components.replication.summary_sha256",
    ),
}

PLAYBACK_CONTEXT = {
    "id": "context",
    "title": "Recorded constraints and limitations",
    "presentation": "Quoted from the snapshot as recorded.",
    "recorded": (
        "summary.constraints",
        "summary.handoff.invariants.synthetic_nfs_contract_only",
        "summary.limitations",
        "summary.run_fingerprint",
    ),
}

_MISSING = object()


def _recorded_value(snapshot: dict, path: str):
    value = snapshot
    for key in path.split("."):
        if not isinstance(value, dict):
            return _MISSING
        value = value.get(key, _MISSING)
        if value is _MISSING:
            return _MISSING
    return value


def _playback_group(snapshot: dict, group: dict) -> dict:
    recorded = []
    for path in group["recorded"]:
        value = _recorded_value(snapshot, path)
        if value is _MISSING:
            raise ValueError(f"retained proof lacks recorded field {path}")
        recorded.append({"path": path, "value": value})
    return {
        "id": group["id"],
        "title": group["title"],
        "presentation": group["presentation"],
        "recorded": recorded,
    }


def proof_playback(snapshot: dict) -> dict:
    """Group retained snapshot fields for display; never computes new results."""
    handoff = snapshot["summary"]["handoff"]
    source, replication = handoff["source"], handoff["replication"]
    if (
        source["sha256"] != replication["target_sha256"]
        or source["byte_size"] != replication["target_byte_size"]
    ):
        raise ValueError("retained proof contradicts itself")
    return {
        "kind": "recorded-playback",
        "executes": False,
        "steps": [_playback_group(snapshot, step) for step in PLAYBACK_STEPS],
        "aggregate": _playback_group(snapshot, PLAYBACK_AGGREGATE),
        "context": _playback_group(snapshot, PLAYBACK_CONTEXT),
    }


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
        playback = proof_playback(data)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise HTTPException(
            status_code=503, detail="Retained proof unavailable or unverified"
        ) from None
    return {
        "snapshot": data,
        "provenance": provenance,
        "playback": playback,
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
