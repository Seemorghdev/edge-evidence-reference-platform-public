"""Deterministic read-only reasoning owned by the Edge Agent service."""

from __future__ import annotations

from edge_evidence_contracts.models import AgentInspection, ArtifactProjection, ArtifactState


def inspect_artifact(artifact: ArtifactProjection) -> AgentInspection:
    if artifact.state is ArtifactState.COMPLETE:
        return AgentInspection(
            artifact_id=artifact.artifact_id,
            classification="healthy-complete",
            explanation=(
                "This example finished successfully. You can review it without changing anything."
            ),
        )
    if artifact.state is ArtifactState.DEFERRED:
        return AgentInspection(
            artifact_id=artifact.artifact_id,
            classification="bounded-defer",
            explanation=(
                "This example is waiting. I can explain why, but I cannot restart it or change "
                "anything."
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
            classification="prepared-awaiting-catch-up",
            explanation=(
                "This example is set up, but has not finished processing."
            ),
            proposal={"action": "inspect-worker-readiness", "execution": "read-only"},
            requires_human_approval=True,
        )
    return AgentInspection(
        artifact_id=artifact.artifact_id,
        classification="attention-required",
        explanation=(
            "This example is not finished. Review its saved result before taking action."
        ),
        proposal={"action": "collect-public-summary", "execution": "read-only"},
        requires_human_approval=True,
    )
