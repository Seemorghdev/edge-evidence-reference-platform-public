#!/usr/bin/env python3
"""Install development tooling and each independent workspace project."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECTS = (
    Path("packages/shared-contracts"),
    Path("services/evidence-api"),
    Path("services/edge-agent"),
    Path("services/web-ui"),
    Path("tools/integration-runner"),
    Path("tools/load-generator"),
)


def install(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "pip", "install", *args], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Install root lint/test/build dependencies before workspace projects.",
    )
    args = parser.parse_args()

    if args.dev:
        install("-e", ".[dev]")
    install("-e", str(PROJECTS[0]))
    for project in PROJECTS[1:]:
        install("--no-deps", "-e", str(project))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
