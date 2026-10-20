"""Fail image build when the installed environment differs from the hash-locked runtime."""

import re
from importlib import metadata
from pathlib import Path

LOCK = Path(__file__).resolve().parent.parent / "requirements-hosted-linux-amd64.lock"


def pinned(line):
    match = re.fullmatch(
        r"([A-Za-z][A-Za-z0-9_-]*)==([A-Za-z0-9_.+]+) --hash=sha256:([0-9a-f]{64})", line
    )
    if not match:
        raise ValueError("A requirements line must contain one exact version and SHA-256 hash")
    return match.group(1).lower().replace("_", "-"), match.group(2)


def verify():
    rows = [
        line.strip()
        for line in LOCK.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not rows or rows.pop(0) != "--only-binary=:all:":
        raise ValueError("wheel-only lock flag is required")
    expected = dict(pinned(line) for line in rows)
    if len(expected) != len(rows) or len(rows) != 17:
        raise ValueError("missing or duplicate locked dependency")
    installed = {
        d.metadata["Name"].lower().replace("_", "-"): d.version for d in metadata.distributions()
    }
    for name, version in expected.items():
        if installed.get(name) != version:
            raise ValueError(f"{name}: expected {version}; installed {installed.get(name)}")
    extras = set(installed) - set(expected) - {"pip"}
    if extras:
        raise ValueError(f"unexpected runtime distributions: {sorted(extras)}")
    if {"google-adk", "litellm", "ollama", "openai", "pytest", "playwright"} & set(installed):
        raise ValueError("forbidden model/test distribution")
    return expected


if __name__ == "__main__":
    print("Locked runtime:", verify())
