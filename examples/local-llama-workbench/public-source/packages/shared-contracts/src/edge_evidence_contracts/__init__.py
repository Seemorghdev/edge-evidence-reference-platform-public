"""Stable contracts shared across independently packaged platform services."""

from .clients import EdgeAgentClient, EvidenceApiClient
from .components import (
    ComponentManifest,
    ProcessorRunSummary,
    load_component,
    load_components,
    load_processor_summary,
    render_command,
    render_container_command,
    render_read_only_command,
)
from .models import (
    AgentInspection,
    ArtifactProjection,
    ArtifactState,
    EvidenceReceipt,
    ProcessorSummary,
    ReplicationSummary,
)

__all__ = [
    "AgentInspection",
    "ArtifactProjection",
    "ArtifactState",
    "ComponentManifest",
    "EdgeAgentClient",
    "EvidenceApiClient",
    "EvidenceReceipt",
    "ProcessorRunSummary",
    "ProcessorSummary",
    "ReplicationSummary",
    "load_component",
    "load_components",
    "load_processor_summary",
    "render_command",
    "render_container_command",
    "render_read_only_command",
]
