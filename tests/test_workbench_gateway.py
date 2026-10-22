import hashlib
from unittest.mock import patch

from edge_evidence_web_ui.workbench import gateway
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
    assert "No new copy check." in page.text
    assert "does not run workers or reread the destination" in page.text
    assert "Recorded digest check" in page.text
    assert client.get("/static/workbench.css").status_code == 200
    script = client.get("/static/workbench.js")
    assert script.status_code == 200
    assert "Inspector response matched the selected synthetic record" in script.text
    assert "Stored bytes and external copies were not checked" in script.text
    assert "Retained JSON SHA-256 checked" in script.text
    assert "Verified response bound to selected record" not in script.text


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
