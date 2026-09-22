from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy/compose/docker-compose.yml"


def test_projection_contains_only_application_facing_top_level_surfaces() -> None:
    assert not (ROOT / "ops").exists()
    assert not (ROOT / "terraform").exists()
    assert not (ROOT / "STATUS.md").exists()
    assert not (ROOT / "deploy/kubernetes/project03").exists()


def test_compose_core_is_exactly_three_application_services() -> None:
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    services = compose["services"]
    core = {name for name, spec in services.items() if not spec.get("profiles")}
    assert core == {"evidence-api", "edge-agent", "web-ui"}
    assert set(services) == {
        "evidence-api",
        "edge-agent",
        "web-ui",
        "integration-runner",
        "load-generator",
    }
    assert services["edge-agent"]["environment"]["EDGE_AGENT_ENABLE_ADK"] == "0"
    assert "*" not in services["edge-agent"]["environment"]["ALLOWED_ORIGINS"]
    assert "*" not in services["evidence-api"]["environment"]["ALLOWED_ORIGINS"]


def test_ci_is_read_only_application_validation() -> None:
    text = (ROOT / ".github/workflows/required.yml").read_text(encoding="utf-8").lower()
    forbidden_commands = (
        "terraform",
        "kubectl",
        "gcloud ",
        "docker push",
        "gh release",
        "workflow_dispatch",
    )
    for forbidden in forbidden_commands:
        assert forbidden not in text


def test_generic_kubernetes_intent_contains_no_public_exposure_resource() -> None:
    rendered = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "deploy/kubernetes/base").glob("*.yaml"))
    )
    assert "type: LoadBalancer" not in rendered
    assert "kind: Ingress" not in rendered
