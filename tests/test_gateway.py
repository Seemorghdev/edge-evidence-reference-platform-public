from edge_evidence_web_ui.gateway import app as gateway_app
from fastapi.testclient import TestClient


def test_gateway_serves_ui_and_same_origin_service_routes() -> None:
    client = TestClient(gateway_app)

    page = client.get("/")
    assert page.status_code == 200
    assert 'data-view="inspect"' in page.text
    assert 'data-view="proof"' in page.text
    assert 'data-view="ask"' in page.text
    assert "no model runs on this page" in page.text
    assert "runs no worker, reads no target and calls no model" in page.text

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
    assert "does not by itself prove that every stored copy matches" in results[0]["explanation"]
    assert "does not retry automatically" in results[1]["explanation"]
    assert "not that it completed" in results[1]["explanation"]
    assert "does not start work automatically" in results[2]["explanation"]
    assert "example ID and content fingerprint" in results[2]["explanation"]


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
