import json

import pytest
from edge_evidence_contracts.models import (
    AgentInspection,
    ArtifactProjection,
    ArtifactState,
    InspectionClassification,
)
from edge_evidence_edge_agent.app import app as agent_app
from edge_evidence_edge_agent.core import inspect_artifact
from fastapi.testclient import TestClient
from pydantic import ValidationError

EXPECTED = {
    ArtifactState.COMPLETE: InspectionClassification.HEALTHY_COMPLETE,
    ArtifactState.DEFERRED: InspectionClassification.BOUNDED_DEFER,
    ArtifactState.PREPARED: InspectionClassification.PREPARED_AWAITING_CATCH_UP,
    ArtifactState.PROCESSING: InspectionClassification.PROCESSING_IN_PROGRESS,
    ArtifactState.FAILED: InspectionClassification.FAILED_RECORDED,
}

# Words that tie an explanation to one interface rather than to the record.
SCREEN_WORDS = ("this page", "technical details", "click", "button", "tab", "below", "above")


def _projection(state: ArtifactState) -> ArtifactProjection:
    return ArtifactProjection(
        artifact_id="art_demo0001",
        state=state,
        digest="sha256:" + "a" * 64,
        created_at="2026-01-01T00:00:00Z",
        snapshot_eligible=state is ArtifactState.COMPLETE,
    )


def test_every_artifact_state_has_an_explicit_classification():
    assert set(EXPECTED) == set(ArtifactState)
    for state, classification in EXPECTED.items():
        result = inspect_artifact(_projection(state))
        assert result.classification is classification
        assert result.classification is not InspectionClassification.ATTENTION_REQUIRED


@pytest.mark.parametrize("state", list(ArtifactState))
def test_inspection_never_authorizes_mutation(state):
    result = inspect_artifact(_projection(state))
    assert result.mutation_authorized is False
    assert result.requires_human_approval is (state is not ArtifactState.COMPLETE)
    if result.proposal is not None:
        assert result.proposal["execution"] in {"read-only", "external-and-human-authorized"}


@pytest.mark.parametrize("state", list(ArtifactState))
def test_explanations_name_no_interface(state):
    explanation = inspect_artifact(_projection(state)).explanation.lower()
    for word in SCREEN_WORDS:
        assert f" {word} " not in f" {explanation} ", (state, word)


def test_classification_rejects_unlisted_labels():
    with pytest.raises(ValidationError):
        AgentInspection(artifact_id="art_demo0001", classification="looks-fine", explanation="x")


def test_classification_serializes_as_plain_string():
    client = TestClient(agent_app)
    for state, classification in EXPECTED.items():
        payload = _projection(state).model_dump(mode="json")
        response = client.post("/api/v1/inspect", json=payload)
        assert response.status_code == 200
        assert json.loads(response.text)["classification"] == classification.value


def test_openapi_lists_the_allowed_classifications():
    schema = TestClient(agent_app).get("/openapi.json").json()
    allowed = schema["components"]["schemas"]["InspectionClassification"]["enum"]
    assert allowed == [member.value for member in InspectionClassification]


def test_package_exports_inspection_classification():
    import edge_evidence_contracts

    assert "InspectionClassification" in edge_evidence_contracts.__all__
    assert edge_evidence_contracts.InspectionClassification is InspectionClassification
