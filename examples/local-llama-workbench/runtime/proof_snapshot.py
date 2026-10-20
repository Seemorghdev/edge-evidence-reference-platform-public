"""Offline-only projection of the separate, immutable showcase response.

No network I/O; never feeds inspector tools, model context, or turn snapshots.
A supported stage needs every required field: a top-level pass label alone is not proof.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

PROOF_DIR = Path(__file__).resolve().parents[1] / "proof"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ProofUnavailable(ValueError):
    """The retained, fixed-location proof cannot be trusted for display."""


def _obj(value):
    return value if isinstance(value, dict) else {}


def _at(value, *keys):
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _equals(value, expected):
    return None if value is None else (type(value) is type(expected) and value == expected)


def _field(value, key, expected):
    if not isinstance(value, dict) or key not in value:
        return None
    return _equals(value[key], expected) if expected is not None else value[key] is None


def _digest(value):
    if value is None:
        return None
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _same_digest(a, b):
    if a is None or b is None:
        return None
    return _digest(a) is True and _digest(b) is True and a == b


def _same_size(a, b):
    if a is None or b is None:
        return None
    return type(a) is int and type(b) is int and a > 0 and a == b


def _verdict(*checks):
    if any(v is False for v in checks):
        return "contradicted"
    if not checks or any(v is None for v in checks):
        return "not_established"
    return "supported"


def project(payload):
    """Derive five bounded stages, never infer results from absent fields."""
    if not isinstance(payload, dict):
        raise ProofUnavailable("Proof response is not an object")
    summary = _obj(payload.get("summary"))
    handoff = _obj(summary.get("handoff"))
    source = _obj(handoff.get("source"))
    repl = _obj(handoff.get("replication"))
    authority = _obj(repl.get("authority"))
    components = _obj(summary.get("components"))
    processor = _obj(components.get("processor"))
    first = _obj(repl.get("first_run"))
    verification = _obj(repl.get("verification"))
    replay = _obj(repl.get("replay"))
    inv = _obj(handoff.get("invariants"))
    root = (
        _field(payload, "status", "pass"),
        _field(payload, "mode", "synthetic-stateless"),
        _field(summary, "schema_version", 1),
        _field(summary, "status", "pass"),
        _field(handoff, "schema_version", 1),
        _field(handoff, "status", "pass"),
    )
    src_digest = source.get("sha256")
    target_digest = repl.get("target_sha256")
    src_size = source.get("byte_size")
    target_size = repl.get("target_byte_size")
    steps = {
        "processor": _verdict(*root, _field(processor,"status","pass"),
            _same_digest(src_digest, processor.get("output_sha256")),
            _field(source,"processor_output_artifact_id",f"sha256:{src_digest}") if _digest(src_digest) else None),
        "handoff": _verdict(*root, _field(inv,"processor_output_was_replication_source",True),
            _same_digest(src_digest, authority.get("expected_sha256")),
            _same_size(src_size, authority.get("expected_byte_size"))),
        "replication": _verdict(*root, _field(_obj(components.get("replication")),"status","pass"),
            _field(first,"status","pass"),_field(first,"inserted",1),
            _field(first,"published",1),_field(first,"verified",1),
            _field(inv,"immutable_create_performed",True),
            _field(inv,"target_bytes_match_processor_output",True),
            _same_digest(src_digest,target_digest),
            _same_size(src_size,target_size)),
        "readback": _verdict(*root, _field(inv,"independent_readback_verified",True),
            _field(verification,"status","pass"),_field(verification,"verified",1),
            _field(authority,"state","VERIFIED"),_field(authority,"last_error",None),
            _same_digest(authority.get("expected_sha256"),target_digest)),
        "replay": _verdict(*root, _field(replay,"status","pass"),
            _field(replay,"inserted",0),_field(replay,"published",0),
            _field(replay,"adopted",0),_field(inv,"exact_replay_is_noop",True)),
    }
    return {"steps":steps,
        "overall":"contradicted" if "contradicted" in steps.values() else
            "not_established" if "not_established" in steps.values() else "supported",
        "source_sha256":src_digest if _digest(src_digest) else None,
        "target_sha256":target_digest if _digest(target_digest) else None,
        "source_bytes":src_size if type(src_size) is int and src_size >= 0 else None,
        "target_bytes":target_size if type(target_size) is int and target_size >= 0 else None,
        "first_published":first.get("published") if type(first.get("published")) is int else None,
        "first_verified":first.get("verified") if type(first.get("verified")) is int else None,
        "readback_verified":verification.get("verified") if type(verification.get("verified")) is int else None,
        "replay_published":replay.get("published") if type(replay.get("published")) is int else None,
        "replay_verified":replay.get("verified") if type(replay.get("verified")) is int else None,
        "target_id":repl.get("target_id") if isinstance(repl.get("target_id"),str) else None}


def load_snapshot(root=PROOF_DIR):
    """Reads only two fixed bundled files and verifies committed-byte checksum."""
    try:
        raw = (root / "showcase-response.json").read_bytes()
        provenance = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
        if not isinstance(provenance,dict) or provenance.get("schema_version") != 1:
            raise ProofUnavailable("Proof provenance schema unavailable")
        digest = provenance.get("snapshot_sha256")
        if not isinstance(digest,str) or not SHA256.fullmatch(digest):
            raise ProofUnavailable("Proof snapshot digest missing")
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ProofUnavailable("Proof snapshot digest mismatch")
        response = json.loads(raw.decode("utf-8"))
        if not isinstance(response,dict) or not isinstance(response.get("summary"),dict):
            raise ProofUnavailable("Proof response schema unavailable")
        if response.get("summary",{}).get("schema_version") != provenance.get("schema_version_handled"):
            raise ProofUnavailable("Proof response schema version mismatch")
        return {"snapshot": response, "provenance": provenance, "projection": project(response)}
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise ProofUnavailable("Retained proof files unavailable or malformed") from exc
