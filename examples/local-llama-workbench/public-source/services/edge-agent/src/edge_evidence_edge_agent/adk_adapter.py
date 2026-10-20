"""Optional ADK adapter with an explicit credential-free default-off gate."""

from __future__ import annotations

import os
from typing import Any

from edge_evidence_contracts.models import ArtifactProjection

from .core import inspect_artifact


def inspect_artifact_tool(artifact: dict[str, Any]) -> dict[str, Any]:
    projection = ArtifactProjection.model_validate(artifact)
    return inspect_artifact(projection).model_dump(mode="json")


def build_adk_agent() -> Any | None:
    if os.getenv("EDGE_AGENT_ENABLE_ADK", "0") != "1":
        return None
    try:
        from google.adk import Agent
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install the 'adk' extra to enable the ADK adapter") from exc

    model = os.environ.get("EDGE_AGENT_MODEL")
    if not model:
        raise RuntimeError("EDGE_AGENT_MODEL must be set when ADK mode is explicitly enabled")

    return Agent(
        name="edge_evidence_inspector",
        model=model,
        instruction=(
            "Inspect only the supplied public synthetic projection. Use the read-only tool. "
            "Never claim mutation authority, execute workers, contact providers, or imply approval."
        ),
        tools=[inspect_artifact_tool],
    )


root_agent = build_adk_agent()
