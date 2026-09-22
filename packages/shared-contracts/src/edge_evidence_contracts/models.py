"""Stable public models used by the local reference platform."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ArtifactState(StrEnum):
    PREPARED = "prepared"
    PROCESSING = "processing"
    COMPLETE = "complete"
    DEFERRED = "deferred"
    FAILED = "failed"


class ArtifactProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(pattern=r"^art_[a-z0-9]{8,64}$")
    state: ArtifactState
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_at: datetime
    source: str = Field(default="synthetic", pattern=r"^synthetic$")
    snapshot_eligible: bool
    labels: dict[str, str] = Field(default_factory=dict)


class ProcessorSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    already_complete: int = Field(ge=0)
    prepared_resumed: int = Field(ge=0)
    newly_completed: int = Field(ge=0)
    deferred: int = Field(ge=0)
    remaining: int = Field(ge=0)


class ReplicationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    created: int = Field(ge=0)
    adopted_exact: int = Field(ge=0)
    verified: int = Field(ge=0)
    collisions_refused: int = Field(ge=0)


class EvidenceReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_id: str = Field(pattern=r"^rcpt_[a-z0-9]{8,64}$")
    artifact_id: str = Field(pattern=r"^art_[a-z0-9]{8,64}$")
    status: str
    issued_at: datetime
    processor: ProcessorSummary
    replication: ReplicationSummary
    provenance: dict[str, str]


class AgentInspection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    classification: str
    explanation: str
    proposal: dict[str, Any] | None = None
    mutation_authorized: bool = False
    requires_human_approval: bool = False


def utcnow() -> datetime:
    return datetime.now(UTC)
