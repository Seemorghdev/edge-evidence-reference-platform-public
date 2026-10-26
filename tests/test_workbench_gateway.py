import ast
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from edge_evidence_web_ui.workbench import gateway
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient


def test_native_services_and_read_only_routes():
    client = TestClient(gateway.app)
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json()["authority"] == "synthetic-only"
    artifacts = client.get("/api/v1/artifacts").json()
    assert len(artifacts) == 3
    for artifact in artifacts:
        response = client.post("/api/v1/inspect", json=artifact)
        assert response.status_code == 200
        assert response.json()["mutation_authorized"] is False
        assert response.json()["artifact_id"] == artifact["artifact_id"]
    for route in ["/api/v1/demo/reset", "/api/ask", "/api/model/prepare", "/api/cancel"]:
        assert client.post(route, json={}).status_code == 404
    assert client.get("/api/review/capabilities").json() == {
        "mode": "hosted",
        "inspect": "deterministic-read-only",
        "proof": "retained-synthetic",
        "llama": "local-only-unavailable-here",
        "test_fixture_services": False,
    }


def test_served_ui_and_assets():
    client = TestClient(gateway.app)
    page = client.get("/")
    assert page.status_code == 200
    assert "connect-src 'self'" in page.headers["content-security-policy"]
    for marker in ['data-view="inspect"', 'data-view="proof"', 'data-view="ask"']:
        assert marker in page.text
    assert "no model runs on this page" in page.text
    assert "no interactive model or generated answers" in page.text
    assert client.get("/static/workbench.css").status_code == 200
    assert client.get("/static/workbench.js").status_code == 200


def test_retained_proof_and_corruption_fail_closed():
    client = TestClient(gateway.app)
    response = client.get("/api/review/proof")
    assert response.status_code == 200
    result = response.json()
    assert result["verification"]["bytes_sha256_checked"] is True
    assert result["snapshot"]["cached"] is True
    assert result["provenance"]["execution_time_utc"] is None
    assert hashlib.sha256(gateway.PROOF_PATH.read_bytes()).hexdigest() == (
        "e0418735bb2f2b9a40a4b0fb32222daf8dd45b69cb5e9c821a74ab442ab10519"
    )
    with patch.object(type(gateway.PROOF_PATH), "read_bytes", return_value=b"{}"):
        assert client.get("/api/review/proof").status_code == 503


def _resolve(snapshot, path):
    value = snapshot
    for key in path.split("."):
        assert isinstance(value, dict) and key in value, path
        value = value[key]
    return value


def test_proof_playback_quotes_only_recorded_fields():
    client = TestClient(gateway.app)
    result = client.get("/api/review/proof").json()
    snapshot, playback = result["snapshot"], result["playback"]
    assert playback["kind"] == "recorded-playback"
    assert playback["executes"] is False
    assert [step["title"] for step in playback["steps"]] == [
        "Processor",
        "Handoff",
        "Replication",
        "Readback",
        "Replay",
    ]
    groups = playback["steps"] + [playback["aggregate"], playback["context"]]
    for group in groups:
        assert group["recorded"], group["id"]
        assert group["presentation"]
        for field in group["recorded"]:
            assert field["value"] == _resolve(snapshot, field["path"])
    replay = {f["path"].rsplit(".", 1)[1]: f["value"] for f in playback["steps"][4]["recorded"]}
    assert replay["published"] == 0 and replay["inserted"] == 0


def test_proof_playback_missing_field_fails_closed():
    client = TestClient(gateway.app)
    broken = gateway.PLAYBACK_STEPS + (
        {
            "id": "absent",
            "title": "Absent",
            "presentation": "Not in the snapshot.",
            "recorded": ("summary.handoff.replication.not_recorded",),
        },
    )
    with patch.object(gateway, "PLAYBACK_STEPS", broken):
        assert client.get("/api/review/proof").status_code == 503


def test_proof_playback_refuses_contradictory_snapshot():
    snapshot = json.loads(gateway.PROOF_PATH.read_bytes())
    snapshot["summary"]["handoff"]["replication"]["target_byte_size"] += 1
    with pytest.raises(ValueError):
        gateway.proof_playback(snapshot)


def test_gateway_route_allowlist_unchanged():
    paths = {route.path for route in gateway.app.routes if isinstance(route, APIRoute)}
    assert paths == {
        "/healthz",
        "/",
        "/favicon.ico",
        "/api/review/capabilities",
        "/api/review/proof",
        "/readyz",
        "/api/v1/artifacts",
        "/api/v1/artifacts/{artifact_id}",
        "/api/v1/receipts",
        "/api/v1/receipts/{receipt_id}",
        "/health",
        "/api/v1/inspect",
    }


def test_gateway_imports_no_worker_or_model_modules():
    tree = ast.parse(Path(gateway.__file__).read_text(encoding="utf8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {
        "__future__",
        "hashlib",
        "json",
        "pathlib",
        "edge_evidence_edge_agent",
        "edge_evidence_evidence_api",
        "fastapi",
    }


def test_served_proof_playback_labels():
    page = TestClient(gateway.app).get("/").text
    assert 'id="proof-steps"' in page
    assert "Playback of a recorded result." in page
    assert "runs no worker, reads no target and calls no model" in page
    assert page.count('<th scope="col">recorded value</th>') >= 3
    assert "pass recorded; steps not retained" in page
    assert "<em>Note</em>" in page
