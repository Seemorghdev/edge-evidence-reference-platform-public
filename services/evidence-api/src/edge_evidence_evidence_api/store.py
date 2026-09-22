"""Disposable in-memory store owned by the Evidence API service."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime

from edge_evidence_contracts.models import (
    ArtifactProjection,
    ArtifactState,
    EvidenceReceipt,
    ProcessorSummary,
    ReplicationSummary,
)


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class SyntheticStore:
    _artifacts: dict[str, ArtifactProjection] = field(default_factory=dict)
    _receipts: dict[str, EvidenceReceipt] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def reset(self) -> None:
        with self._lock:
            self._artifacts.clear()
            self._receipts.clear()
            for index, state in enumerate(
                (ArtifactState.COMPLETE, ArtifactState.DEFERRED, ArtifactState.PREPARED),
                start=1,
            ):
                artifact_id = f"art_demo{index:04d}"
                artifact = ArtifactProjection(
                    artifact_id=artifact_id,
                    state=state,
                    digest=_digest(artifact_id),
                    created_at=datetime(2026, 1, index, tzinfo=UTC),
                    snapshot_eligible=state is ArtifactState.COMPLETE,
                    labels={"scenario": state.value, "authority": "synthetic"},
                )
                self._artifacts[artifact_id] = artifact
                if state is ArtifactState.COMPLETE:
                    receipt = EvidenceReceipt(
                        receipt_id=f"rcpt_demo{index:04d}",
                        artifact_id=artifact_id,
                        status="verified",
                        issued_at=datetime(2026, 1, index, 0, 5, tzinfo=UTC),
                        processor=ProcessorSummary(
                            status="complete",
                            already_complete=0,
                            prepared_resumed=0,
                            newly_completed=1,
                            deferred=0,
                            remaining=0,
                        ),
                        replication=ReplicationSummary(
                            status="verified",
                            created=1,
                            adopted_exact=0,
                            verified=1,
                            collisions_refused=0,
                        ),
                        provenance={
                            "source": "synthetic-fixture",
                            "processor_contract": "v1",
                            "replication_contract": "v1",
                        },
                    )
                    self._receipts[receipt.receipt_id] = receipt

    def list_artifacts(self) -> list[ArtifactProjection]:
        with self._lock:
            return sorted(self._artifacts.values(), key=lambda item: item.artifact_id)

    def get_artifact(self, artifact_id: str) -> ArtifactProjection | None:
        with self._lock:
            return self._artifacts.get(artifact_id)

    def list_receipts(self) -> list[EvidenceReceipt]:
        with self._lock:
            return sorted(self._receipts.values(), key=lambda item: item.receipt_id)

    def get_receipt(self, receipt_id: str) -> EvidenceReceipt | None:
        with self._lock:
            return self._receipts.get(receipt_id)


store = SyntheticStore()
store.reset()
