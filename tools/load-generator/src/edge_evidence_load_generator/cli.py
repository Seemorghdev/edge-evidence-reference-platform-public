"""Bounded synthetic HTTP load generator."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Sequence

from edge_evidence_contracts.clients import EvidenceApiClient


def execute(base_url: str, count: int, delay_ms: int) -> dict[str, int | str]:
    if count < 1 or count > 1000:
        raise ValueError("count must be between 1 and 1000")
    successes = 0
    failures = 0
    with EvidenceApiClient(base_url) as client:
        for _ in range(count):
            try:
                client.list_artifacts()
                successes += 1
            except Exception:
                failures += 1
            if delay_ms:
                time.sleep(delay_ms / 1000)
    return {
        "status": "complete",
        "requests": count,
        "successes": successes,
        "failures": failures,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--delay-ms", type=int, default=50)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = execute(args.base_url, args.count, args.delay_ms)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
