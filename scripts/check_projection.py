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
    if HEX40.search(scanned_text):
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
