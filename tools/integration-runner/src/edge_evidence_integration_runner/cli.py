"""Credential-free integration command for the three-service product."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from edge_evidence_contracts.clients import EdgeAgentClient, EvidenceApiClient


def run_services(
    *,
    evidence_api_url: str,
    edge_agent_url: str,
    output: Path,
) -> dict[str, object]:
    with EvidenceApiClient(evidence_api_url) as evidence_api:
        assert evidence_api.health()["status"] == "ok"
        artifacts = evidence_api.list_artifacts()
    with EdgeAgentClient(edge_agent_url) as edge_agent:
        health = edge_agent.health()
        assert health["status"] == "ok"
        assert health["mutation_authorized"] is False
        inspections = [edge_agent.inspect(artifact) for artifact in artifacts]

    result: dict[str, object] = {
        "status": "synthetic-contract-valid",
        "artifact_count": len(artifacts),
        "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
        "inspections": [inspection.model_dump(mode="json") for inspection in inspections],
        "services_exercised_over_http": True,
        "authority": "synthetic-only",
        "mutation_authorized": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Exercise the public service contracts")
    run_parser.add_argument("--evidence-api-url", default="http://localhost:8080")
    run_parser.add_argument("--edge-agent-url", default="http://localhost:8081")
    run_parser.add_argument("--output", type=Path, default=Path("build/integration/result.json"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_services(
        evidence_api_url=args.evidence_api_url,
        edge_agent_url=args.edge_agent_url,
        output=args.output,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
