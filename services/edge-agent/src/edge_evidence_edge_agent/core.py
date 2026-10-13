"""Deterministic read-only reasoning owned by the Edge Agent service."""

from __future__ import annotations

from edge_evidence_contracts.models import AgentInspection, ArtifactProjection, ArtifactState


def inspect_artifact(artifact: ArtifactProjection) -> AgentInspection:
    if artifact.state is ArtifactState.COMPLETE:
        return AgentInspection(
            artifact_id=artifact.artifact_id,
            classification="healthy-complete",
            explanation=(
                "Complete means this synthetic example has a recorded finished state; it does "
                "not by itself prove that every stored copy matches. Nothing runs automatically: "
                "this page only reads a fixed example, and a reviewer should inspect the "
                "displayed state and, under Technical details, the example ID and content "
                "fingerprint before drawing conclusions."
            ),
        )
    if artifact.state is ArtifactState.DEFERRED:
        return AgentInspection(
            artifact_id=artifact.artifact_id,
            classification="bounded-defer",
            explanation=(
                "Deferred means this example is waiting for a later step, not that it completed. "
                "The system does not retry automatically because a repeat could have side effects "
                "or obscure why it paused. A reviewer can inspect the displayed state and, under "
                "Technical details, the example ID and content fingerprint, then decide separately "
                "whether any action is appropriate."
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
                "Prepared means the example is set up for processing, but no completed result is "
                "shown. The system does not start work automatically because processing may have "
                "side effects and should follow an explicit decision. A reviewer can inspect the "
                "displayed state and, under Technical details, the example ID and content "
                "fingerprint; this page does not run the work."
            ),
            proposal={"action": "inspect-worker-readiness", "execution": "read-only"},
            requires_human_approval=True,
        )
    return AgentInspection(
        artifact_id=artifact.artifact_id,
        classification="attention-required",
        explanation=(
            "This example does not match a completed, deferred, or prepared state. The system "
            "does not guess or act automatically. A reviewer can inspect the displayed state and "
                "example ID and content fingerprint under Technical details, then consult source "
                "evidence before deciding what to do."
        ),
        proposal={"action": "collect-public-summary", "execution": "read-only"},
        requires_human_approval=True,
    )
