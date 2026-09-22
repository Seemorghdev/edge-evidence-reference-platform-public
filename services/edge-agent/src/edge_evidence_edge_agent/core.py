"""Deterministic read-only reasoning owned by the Edge Agent service."""

from __future__ import annotations

from edge_evidence_contracts.models import AgentInspection, ArtifactProjection, ArtifactState


def inspect_artifact(artifact: ArtifactProjection) -> AgentInspection:
    if artifact.state is ArtifactState.COMPLETE:
        return AgentInspection(
            artifact_id=artifact.artifact_id,
            classification="healthy-complete",
            explanation=(
                "The synthetic projection is complete and eligible for snapshot inspection."
            ),
        )
    if artifact.state is ArtifactState.DEFERRED:
        return AgentInspection(
            artifact_id=artifact.artifact_id,
            classification="bounded-defer",
            explanation=(
                "The component contract reports deferred work. The agent can explain the state "
                "but cannot execute a worker or mutate authority."
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
            explanation="A prepared synthetic artifact has not yet reached a completed projection.",
            proposal={"action": "inspect-worker-readiness", "execution": "read-only"},
            requires_human_approval=True,
        )
    return AgentInspection(
        artifact_id=artifact.artifact_id,
        classification="attention-required",
        explanation=(
            "The projection is not complete. Inspect stable component output before action."
        ),
        proposal={"action": "collect-public-summary", "execution": "read-only"},
        requires_human_approval=True,
    )
