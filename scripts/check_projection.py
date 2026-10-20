#!/usr/bin/env python3
"""Fail closed if excluded history/control-plane material enters this projection."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()

FORBIDDEN_TOP_LEVEL = {"ops", "terraform"}
FORBIDDEN_PATH_FRAGMENTS = ("project03", "gcp-ops")
FORBIDDEN_TEXT = (
    ".pkg.dev",
    ".run.app",
    "iam.gserviceaccount.com",
    "workload identity federation",
    "wif",
    "github.com/seemorghdev/",
    "BEGIN PRIVATE KEY",
    "client_secret",
    "access_token",
    "/issues/",
    "/pull/",
)
# Recruiter navigation is intentionally limited to these exact public repositories.
# The strings are exempted from the owner-repository text rule only in the UI template
# and its focused gateway test; every URL variant and all other forbidden-content rules
# remain enforced everywhere.
APPROVED_PUBLIC_REPOSITORY_LINKS = {
    "services/web-ui/src/edge_evidence_web_ui/templates/index.html": {
        "https://github.com/Seemorghdev/edge-evidence-processor-public",
        "https://github.com/Seemorghdev/edge-evidence-replication-projection",
        "https://github.com/Seemorghdev/edge-evidence-reference-platform-public",
    },
    "tests/test_gateway.py": {
        "https://github.com/Seemorghdev/edge-evidence-processor-public",
        "https://github.com/Seemorghdev/edge-evidence-replication-projection",
        "https://github.com/Seemorghdev/edge-evidence-reference-platform-public",
    },
}

# Exact public-source provenance only; unlisted identities remain forbidden.
APPROVED_SOURCE_IDENTIFIERS = {
    ".github/workflows/gateway-container.yml": ["9334b4966d88416842fb10fe7666da4411bac185"],
    "examples/local-llama-workbench/SOURCE-MANIFEST.json": [
        "0a3203c59765ca3c80e460cb1c96cfbd2d3027ba",
        "1b9f5fe4da58751eadf192d2b37eb78592056646",
        "2e950cf8a3e218e640358b43c38f0ddd6b263e6e",
        "3060e280aa2f6c95fb5e06aed2d253593c507130",
        "35933e6e705c8ac6e4eabca9d677b9fc6dc79f00",
        "37e8a8f9a34ff04eea621d146fea078632ed9125",
        "7a401b9587911cde53029a4008c0c6d60565ff11",
        "92becd047a0f441d74bec58dadc2370acf786eff",
        "998982ccacfd3e9aa13910caceb6eedb9d2f0814",
        "a34aec66288cb5a68f984cdd819cb3bc7d8ba58b",
        "ab99168f00e17ddc87f35c833f6a00bdf68e6e08",
        "ba303c716994ec0520a8151542a3d3be5fd58f5a",
        "d29502cd5b2570517fb2418bd4956cdb9e2fbddf",
        "d645695673349e3947e8e5ae42332d0ac3164cd7",
    ],
    "examples/local-llama-workbench/proof/provenance.json": [
        "531f1f6d500a2b23de354e9f0444adaa782fc1ae"
    ],
    "examples/local-llama-workbench/runtime/boundaries.py": [
        "37e8a8f9a34ff04eea621d146fea078632ed9125"
    ],
    "examples/local-llama-workbench/runtime/case_review.py": [
        "37e8a8f9a34ff04eea621d146fea078632ed9125"
    ],
    "examples/local-llama-workbench/ui/index.html": ["531f1f6d500a2b23de354e9f0444adaa782fc1ae"],
    "services/web-ui/hosted_packaging/PUBLIC-SOURCE-BLOBS.json": [
        "050b93b5a8fab74017f23a771a25e0e04dd71b89",
        "0a3203c59765ca3c80e460cb1c96cfbd2d3027ba",
        "1654e90ab0cba4a0cfb87186e0dc1b2d5f192e29",
        "1b9f5fe4da58751eadf192d2b37eb78592056646",
        "35933e6e705c8ac6e4eabca9d677b9fc6dc79f00",
        "92becd047a0f441d74bec58dadc2370acf786eff",
        "9334b4966d88416842fb10fe7666da4411bac185",
        "9a3ba34fb41192e73448f65e96bf1530c69ddedc",
        "a34aec66288cb5a68f984cdd819cb3bc7d8ba58b",
        "ab99168f00e17ddc87f35c833f6a00bdf68e6e08",
        "ba303c716994ec0520a8151542a3d3be5fd58f5a",
        "d29502cd5b2570517fb2418bd4956cdb9e2fbddf",
        "d645695673349e3947e8e5ae42332d0ac3164cd7",
        "fa3b78686124cd4e12f6cf34cf083eee173d7504",
    ],
    "services/web-ui/src/edge_evidence_web_ui/workbench/retained-provenance.json": [
        "531f1f6d500a2b23de354e9f0444adaa782fc1ae"
    ],
}
APPROVED_PUBLIC_REPOSITORY_LINKS[".github/workflows/gateway-container.yml"] = {
    "https://github.com/Seemorghdev/edge-evidence-reference-platform-public.git"
}
APPROVED_PUBLIC_REPOSITORY_LINKS.update(
    {
        "examples/local-llama-workbench/SOURCE-MANIFEST.json": {
            "https://github.com/Seemorghdev/edge-evidence-reference-platform-public"
        },
        "examples/local-llama-workbench/proof/provenance.json": {
            "https://github.com/Seemorghdev/edge-evidence-showcase"
        },
        "examples/local-llama-workbench/ui/index.html": {
            "https://github.com/Seemorghdev/edge-evidence-showcase/tree/531f1f6d500a2b23de354e9f0444adaa782fc1ae"
        },
        "services/web-ui/src/edge_evidence_web_ui/workbench/index.html": {
            "https://github.com/Seemorghdev/edge-evidence-reference-platform-public/tree/main/examples/local-llama-workbench"
        },
        "services/web-ui/src/edge_evidence_web_ui/workbench/retained-provenance.json": {
            "https://github.com/Seemorghdev/edge-evidence-showcase"
        },
    }
)

GITHUB_REPOSITORY_URL = re.compile(r"https?://github\.com/[^\s\"'<>]+", re.IGNORECASE)
HEX40 = re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])", re.IGNORECASE)
PROJECT_COORDINATE = re.compile(r"\bproject-[a-z0-9-]{8,}\b", re.IGNORECASE)


def iter_text_files() -> list[Path]:
    files: list[Path] = []
    ignored_parts = {".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path == SELF:
            continue
        if any(part in ignored_parts for part in path.parts):
            continue
        files.append(path)
    return files


def validate_text(relative: str, text: str) -> None:
    """Validate one projection file, narrowly permitting recruiter repository links."""
    approved_links = APPROVED_PUBLIC_REPOSITORY_LINKS.get(relative, set())
    repository_urls = GITHUB_REPOSITORY_URL.findall(text)
    unexpected_urls = [url for url in repository_urls if url not in approved_links]
    if unexpected_urls:
        raise ValueError(f"unapproved GitHub repository URL in {relative}")

    scanned_text = text
    for approved_url in repository_urls:
        scanned_text = scanned_text.replace(approved_url, "", 1)

    lowered = scanned_text.lower()
    for fragment in FORBIDDEN_TEXT:
        if fragment.lower() in lowered:
            raise ValueError(f"forbidden projection content in {relative}: {fragment}")
    allowed_ids = set(APPROVED_SOURCE_IDENTIFIERS.get(relative, []))
    if any(match.group().lower() not in allowed_ids for match in HEX40.finditer(scanned_text)):
        raise ValueError(f"commit/tree-shaped identifier present in {relative}")
    if PROJECT_COORDINATE.search(scanned_text):
        raise ValueError(f"project coordinate present in {relative}")


def main() -> int:
    top = {path.name for path in ROOT.iterdir()}
    present = sorted(FORBIDDEN_TOP_LEVEL & top)
    if present:
        raise SystemExit(f"forbidden top-level surfaces present: {present}")

    workflow_dir = ROOT / ".github" / "workflows"
    workflows = sorted(path.name for path in workflow_dir.glob("*.y*ml"))
    if workflows != ["gateway-container.yml", "required.yml"]:
        raise SystemExit(f"unexpected workflow set: {workflows}")

    for path in iter_text_files():
        relative = path.relative_to(ROOT).as_posix()
        lowered_path = relative.lower()
        if any(fragment in lowered_path for fragment in FORBIDDEN_PATH_FRAGMENTS):
            raise SystemExit(f"forbidden path fragment: {relative}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        try:
            validate_text(relative, text)
        except ValueError as error:
            raise SystemExit(str(error)) from error

    print("projection boundary intact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
