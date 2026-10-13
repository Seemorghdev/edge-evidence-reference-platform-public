from edge_evidence_web_ui.gateway import app as gateway_app
from fastapi.testclient import TestClient


def test_gateway_serves_ui_and_same_origin_service_routes() -> None:
    client = TestClient(gateway_app)

    page = client.get("/")
    assert page.status_code == 200
    assert 'const evidenceApi = ""' in page.text
    assert 'const edgeAgent = ""' in page.text

    artifacts = client.get("/api/v1/artifacts")
    assert artifacts.status_code == 200
    payload = artifacts.json()
    assert len(payload) == 3
    assert {item["state"] for item in payload} == {"complete", "deferred", "prepared"}

    explanations = [client.post("/api/v1/inspect", json=artifact) for artifact in payload]
    assert all(response.status_code == 200 for response in explanations)
    results = [response.json() for response in explanations]
    assert [result["artifact_id"] for result in results] == [
        artifact["artifact_id"] for artifact in payload
    ]
    assert all(result["mutation_authorized"] is False for result in results)
    assert all(result["explanation"] for result in results)
    assert "finished successfully" in results[0]["explanation"]
    assert "cannot restart" in results[1]["explanation"]
    assert "has not finished processing" in results[2]["explanation"]


def test_gateway_keeps_cross_origin_and_reset_routes_out_of_scope() -> None:
    client = TestClient(gateway_app)

    assert client.get("/health").json() == {"status": "ok", "mutation_authorized": False}
    assert client.get("/readyz").json() == {
        "status": "ready",
        "authority": "synthetic-only",
    }
    assert client.post("/api/v1/demo/reset").status_code == 404
    preflight = client.options(
        "/api/v1/inspect",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.headers.get("access-control-allow-origin") is None
