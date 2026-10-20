#!/usr/bin/env python3
"""Stage a fail-closed Docker context from an immutable public Git checkout.

No network, private history, model data, test fixtures, or Git working tree copying.
The ten packaged Python modules and three notices come from pinned *Git objects*, with
both Git blob IDs and source commit checked. Immutable source is not a public export.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / "hosted_packaging" / "PUBLIC-SOURCE-BLOBS.json"
LOCAL_ALLOWLIST = (
    "src/edge_evidence_web_ui/__init__.py",
    "src/edge_evidence_web_ui/gateway.py",
    "src/edge_evidence_web_ui/workbench/__init__.py",
    "src/edge_evidence_web_ui/workbench/gateway.py",
    "src/edge_evidence_web_ui/workbench/index.html",
    "src/edge_evidence_web_ui/workbench/retained-proof.json",
    "src/edge_evidence_web_ui/workbench/retained-provenance.json",
    "src/edge_evidence_web_ui/workbench/static/workbench.css",
    "src/edge_evidence_web_ui/workbench/static/workbench.js",
    "Dockerfile.gateway",
    "hosted_packaging/hosted_entrypoint.py",
    "hosted_packaging/runtime_inventory.py",
    "requirements-hosted-linux-amd64.lock",
)
PROOF_SHA = "e0418735bb2f2b9a40a4b0fb32222daf8dd45b69cb5e9c821a74ab442ab10519"


def git(checkout: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(checkout), *args], stderr=subprocess.PIPE)


def git_blob_sha(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\x00" + raw).hexdigest()


def resolve_native_source(checkout: Path, pin: dict) -> dict[str, bytes]:
    if git(checkout, "rev-parse", "HEAD").decode().strip() != pin["revision"]:
        raise ValueError("public source checkout is not pinned")
    if git(checkout, "rev-parse", "--show-toplevel").decode().strip() != str(checkout.resolve()):
        raise ValueError("checkout root mismatch")
    native = {}
    for source, blob in pin["files"].items():
        # git-show HEAD, never working-tree material, prevents local uncommitted leakage.
        raw = git(checkout, "show", f"HEAD:{source}")
        if git_blob_sha(raw) != blob:
            raise ValueError(f"pinned public source blob mismatch: {source}")
        native[source.split("/src/", 1)[1]] = raw
    if len(native) != len(pin["files"]) or len(native) != 10:
        raise ValueError("unexpected native source count")
    return native


def resolve_notices(checkout: Path, pin: dict) -> dict[str, bytes]:
    notices = pin.get("notices", {})
    if set(notices) != {"LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"}:
        raise ValueError("all three upstream notice files must be pinned")
    result = {}
    for source, blob in notices.items():
        raw = git(checkout, "show", f"HEAD:{source}")
        if git_blob_sha(raw) != blob:
            raise ValueError(f"pinned upstream notice blob mismatch: {source}")
        result[source] = raw
    return result


def stage(checkout: Path, output: Path) -> Path:
    pin = json.loads(PIN.read_text())
    checkout = checkout.resolve()
    output = output.resolve()
    if output.exists():
        raise ValueError("build context output exists (refuse reuse; clean manually)")
    if output == ROOT or ROOT in output.parents:
        raise ValueError("output must not be inside candidate source")
    if output == checkout or checkout in output.parents:
        raise ValueError("output must not be inside source checkout")
    native = resolve_native_source(checkout, pin)
    notices = resolve_notices(checkout, pin)
    if (
        hashlib.sha256(
            (ROOT / "src/edge_evidence_web_ui/workbench/retained-proof.json").read_bytes()
        ).hexdigest()
        != PROOF_SHA
    ):
        raise ValueError("retained proof bytes no longer match immutable snapshot")
    output.mkdir(parents=True)
    file_index = {}
    for rel in LOCAL_ALLOWLIST:
        b = (ROOT / rel).read_bytes()
        target = output / ("web-ui/" + rel.removeprefix("src/") if rel.startswith("src/") else rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b)
        file_index[str(target.relative_to(output))] = {
            "sha256": hashlib.sha256(b).hexdigest(),
            "bytes": len(b),
        }
    for rel, b in native.items():
        target = output / "native" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b)
        file_index[str(target.relative_to(output))] = {
            "sha256": hashlib.sha256(b).hexdigest(),
            "bytes": len(b),
        }
    for rel, b in notices.items():
        target = output / "upstream-notices" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b)
        file_index[str(target.relative_to(output))] = {
            "sha256": hashlib.sha256(b).hexdigest(),
            "bytes": len(b),
        }
    # Context is fully synthesized, not an ordinary broad Docker build of PLANNING.
    allowed = set(file_index) | {"CONTEXT-MANIFEST.json"}
    for rel in list(allowed):
        allowed.update(str(p) + "/" for p in Path(rel).parents if str(p) != ".")
    ignore = "# Generated allowlisted runtime context\n**\n" + "".join(
        "!" + p + "\n" for p in sorted(allowed)
    )
    (output / ".dockerignore").write_text(ignore)
    manifest = {
        "public_repository": pin["public_repository"],
        "source_revision": pin["revision"],
        "source_git_blobs": pin["files"],
        "notice_git_blobs": pin["notices"],
        "context_files": file_index,
        "proof_sha256": PROOF_SHA,
        "platform": "linux/amd64",
        "native_package_distribution": (
            "exact committed Python source imported from /app/native; no local pip build"
        ),
    }
    (output / "CONTEXT-MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--public-checkout", type=Path, required=True, help="exact immutable public repo checkout"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="new empty build context outside source trees"
    )
    args = parser.parse_args()
    try:
        result = stage(args.public_checkout, args.output)
    except (AssertionError, FileNotFoundError, subprocess.CalledProcessError, ValueError) as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2
    print(f"Verified 10 source blobs + 3 upstream notices; staged context at {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
