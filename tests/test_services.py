from edge_evidence_contracts.models import ArtifactProjection, ArtifactState
from edge_evidence_edge_agent.app import app as agent_app
from edge_evidence_evidence_api.app import app as evidence_app
from edge_evidence_web_ui.app import app as web_app
from fastapi.testclient import TestClient


def test_evidence_api_behavior_and_health_are_preserved() -> None:
    client = TestClient(evidence_app)
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {
        "status": "ready",
        "authority": "synthetic-only",
    }
    artifacts = client.get("/api/v1/artifacts").json()
    assert len(artifacts) == 3
    assert {item["state"] for item in artifacts} == {"complete", "deferred", "prepared"}


def test_edge_agent_remains_read_only() -> None:
    client = TestClient(agent_app)
    expected_health = {"status": "ok", "mutation_authorized": False}
    assert client.get("/health").json() == expected_health
    assert client.get("/healthz").json() == expected_health
    projection = ArtifactProjection(
        artifact_id="art_demo0001",
        state=ArtifactState.COMPLETE,
        digest="sha256:" + "a" * 64,
        created_at="2026-01-01T00:00:00Z",
        snapshot_eligible=True,
    )
    response = client.post("/api/v1/inspect", json=projection.model_dump(mode="json"))
    assert response.status_code == 200
    assert response.json()["classification"] == "healthy-complete"
    assert response.json()["mutation_authorized"] is False


def test_web_assets_are_served_from_the_web_package() -> None:
    client = TestClient(web_app)
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/").status_code == 200
    assert client.get("/static/style.css").status_code == 200
