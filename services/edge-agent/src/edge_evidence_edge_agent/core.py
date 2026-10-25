"""Deterministic read-only reasoning owned by the Edge Agent service."""

from __future__ import annotations

from edge_evidence_contracts.models import (
    AgentInspection,
    ArtifactProjection,
    ArtifactState,
    InspectionClassification,
)

# Explanations describe the record only. They name no screen, section or control,
# so every interface that displays them can supply its own navigation wording.


def inspect_artifact(artifact: ArtifactProjection) -> AgentInspection:
    if artifact.state is ArtifactState.COMPLETE:
        return AgentInspection(
            artifact_id=artifact.artifact_id,
            classification=InspectionClassification.HEALTHY_COMPLETE,
            explanation=(
                "Complete means this synthetic example has a recorded finished state; it does "
                "not by itself prove that every stored copy matches. The inspector only reads "
                "the record and starts no work. Check the recorded state, example ID and "
                "content fingerprint before drawing conclusions."
            ),
        )
    if artifact.state is ArtifactState.DEFERRED:
        return AgentInspection(
            artifact_id=artifact.artifact_id,
            classification=InspectionClassification.BOUNDED_DEFER,
            explanation=(
                "Deferred means this example is waiting for a later step, not that it completed. "
                "The system does not retry automatically because a repeat could have side effects "
                "or obscure why it paused. Check the recorded state, example ID and content "
                "fingerprint, then decide separately whether any action is appropriate."
            ),
            proposal={
                "action": "review-component-summary",
                "command_template": "processor-worker run --database <PATH> --spool-root <PATH>",
                "execution": "external-and-human-authorized",
            },
            requires_human_approval=True,
        )
    if artifact.state is ArtifactState.PREPARED:
        return AgentInspection(
            artifact_id=artifact.artifact_id,
            classification=InspectionClassification.PREPARED_AWAITING_CATCH_UP,
            explanation=(
                "Prepared means the example is set up for processing, but no completed result is "
                "recorded. The system does not start work automatically because processing may "
                "have side effects and should follow an explicit decision. Check the recorded "
                "state, example ID and content fingerprint; the inspector does not run the work."
            ),
            proposal={"action": "inspect-worker-readiness", "execution": "read-only"},
            requires_human_approval=True,
        )
    if artifact.state is ArtifactState.PROCESSING:
        return AgentInspection(
            artifact_id=artifact.artifact_id,
            classification=InspectionClassification.PROCESSING_IN_PROGRESS,
            explanation=(
                "Processing means the record shows work started and not yet finished. It is "
                "neither a completed result nor a failure. The inspector does not wait for, "
                "resume or retry the work; a later record is needed to show how it ended."
            ),
            proposal={"action": "inspect-worker-readiness", "execution": "read-only"},
            requires_human_approval=True,
        )
    if artifact.state is ArtifactState.FAILED:
        return AgentInspection(
            artifact_id=artifact.artifact_id,
            classification=InspectionClassification.FAILED_RECORDED,
            explanation=(
                "Failed means the record reports that the work did not finish successfully. The "
                "record alone does not say why. The system does not retry automatically; collect "
                "the component summary before deciding whether a retry is safe."
            ),
            proposal={"action": "collect-public-summary", "execution": "read-only"},
            requires_human_approval=True,
        )
    # Unreachable for the current ArtifactState values; kept fail-closed for future states.
    return AgentInspection(
        artifact_id=artifact.artifact_id,
        classification=InspectionClassification.ATTENTION_REQUIRED,
        explanation=(
            "This example does not match a known state. The system does not guess or act "
            "automatically. Consult source evidence before deciding what to do."
        ),
        proposal={"action": "collect-public-summary", "execution": "read-only"},
        requires_human_approval=True,
    )
