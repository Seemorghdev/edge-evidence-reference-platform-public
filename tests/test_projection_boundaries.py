from pathlib import Path

import pytest
import yaml

from scripts.check_projection import validate_text

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy/compose/docker-compose.yml"
GATEWAY_TEST = "tests/test_gateway.py"
GITHUB_ROOT = "https://" + "github.com/"
OWNER = "Seemorgh" + "dev"
APPROVED_PROCESSOR_URL = GITHUB_ROOT + OWNER + "/edge-evidence-processor-public"


def test_projection_contains_only_application_facing_top_level_surfaces() -> None:
    assert not (ROOT / "ops").exists()
    assert not (ROOT / "terraform").exists()
    assert not (ROOT / "STATUS.md").exists()
    assert not (ROOT / "deploy/kubernetes/project03").exists()


def test_projection_guard_allows_exact_recruiter_repository_links_only_in_ui_and_test() -> None:
    template = "services/web-ui/src/edge_evidence_web_ui/templates/index.html"
    processor = APPROVED_PROCESSOR_URL
    replication = GITHUB_ROOT + OWNER + "/edge-evidence-replication-projection"
    reference = GITHUB_ROOT + OWNER + "/edge-evidence-reference-platform-public"

    validate_text(template, " ".join((processor, replication, reference)))
    validate_text(GATEWAY_TEST, " ".join((processor, replication, reference)))


@pytest.mark.parametrize(
    "url",
    [
        GITHUB_ROOT + OWNER + "/edge-evidence-reference-platform",
        GITHUB_ROOT + OWNER + "/edge-evidence-processor-public/tree/main",
        GITHUB_ROOT + OWNER + "/edge-evidence-processor-public?tab=readme",
        GITHUB_ROOT + OWNER + "/edge-evidence-unapproved",
    ],
)
def test_projection_guard_rejects_private_unapproved_and_variant_repository_links(url: str) -> None:
    with pytest.raises(ValueError, match="unapproved GitHub repository URL"):
        validate_text(GATEWAY_TEST, url)


def test_projection_guard_keeps_private_operational_identifiers_forbidden() -> None:
    private_identifier = "iam.gserviceaccount" + ".com"
    with pytest.raises(ValueError, match="forbidden projection content"):
        validate_text(GATEWAY_TEST, private_identifier)


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


def test_gateway_container_ci_builds_and_runs_without_publishing() -> None:
    text = (ROOT / ".github/workflows/gateway-container.yml").read_text(
        encoding="utf-8"
    ).lower()
    assert "docker build" in text
    assert "docker run" in text
    assert "docker push" not in text
    assert "docker login" not in text
    assert "container-browser:" in text


def test_gateway_container_browser_mode_is_event_specific() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/gateway-container.yml").read_text(
            encoding="utf-8"
        )
    )
    steps = workflow["jobs"]["container-browser"]["steps"]
    baseline_checkout = next(
        step for step in steps if step.get("with", {}).get("path") == "baseline"
    )
    baseline_steps = [
        step
        for step in steps
        if step.get("name") in {
            "Install baseline services for before screenshot",
            "Start the three-service baseline",
        }
    ]
    browser_step = next(
        step
        for step in steps
        if step.get("name") == "Browser journey against baseline and container"
    )
    browser_script = (ROOT / "tests/browser_gateway_smoke.py").read_text(encoding="utf-8")

    assert baseline_checkout["if"] == "github.event_name == 'pull_request'"
    assert all(step["if"] == "github.event_name == 'pull_request'" for step in baseline_steps)
    assert browser_step["env"]["COMPARE_BASELINE"] == "${{ github.event_name == 'pull_request' }}"
    assert "if compare_baseline:" in browser_script
    assert 'name="Three examples. One safe workflow."' in browser_script
    assert 'inner_text() == "All 3 synthetic examples are ready."' in browser_script
    assert "exercise_gateway(" in browser_script


def test_generic_kubernetes_intent_contains_no_public_exposure_resource() -> None:
    rendered = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "deploy/kubernetes/base").glob("*.yaml"))
    )
    assert "type: LoadBalancer" not in rendered
    assert "kind: Ingress" not in rendered
