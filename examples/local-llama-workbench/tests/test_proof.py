"""Regression checks for the separate retained synthetic worker snapshot (no network)."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT / "runtime"))
from proof_snapshot import ProofUnavailable, load_snapshot, project
from panel_api import create_app
from panel_supervisor import PanelSupervisor, MockTransport
from fastapi.testclient import TestClient


class ProofSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_snapshot()
        cls.snapshot = cls.data["snapshot"]

    def copy(self):
        return copy.deepcopy(self.snapshot)

    def test_snapshot_source_and_projection(self):
        data = self.data
        self.assertIs(data["snapshot"]["cached"], True)
        self.assertEqual(data["snapshot"]["mode"], "synthetic-stateless")
        self.assertEqual(set(data["projection"]["steps"]), {"processor","handoff","replication","readback","replay"})
        self.assertEqual(set(data["projection"]["steps"].values()), {"supported"})
        self.assertEqual(data["projection"]["source_bytes"], 675)
        self.assertEqual(data["projection"]["target_bytes"], 675)
        self.assertEqual(data["projection"]["first_published"], 1)
        self.assertEqual(data["projection"]["first_verified"], 1)
        self.assertEqual(data["projection"]["readback_verified"], 1)
        self.assertEqual(data["projection"]["replay_published"], 0)
        self.assertEqual(data["projection"]["replay_verified"], 0)
        self.assertEqual(data["projection"]["source_sha256"], data["projection"]["target_sha256"])
        self.assertEqual(data["provenance"]["raw_http_payload_sha256"], data["provenance"]["snapshot_sha256"])
        self.assertEqual(data["provenance"]["source_retrieved_utc"], "2026-10-19T10:55:05Z")
        self.assertIsNone(data["provenance"]["execution_time_utc"])
        self.assertFalse(data["snapshot"]["summary"]["constraints"]["ollama_executed"])

    def test_missing_is_not_failed_readback(self):
        payload=self.copy()
        del payload["summary"]["handoff"]["replication"]["verification"]["verified"]
        self.assertEqual(project(payload)["steps"]["readback"],"not_established")
        payload=self.copy()
        del payload["summary"]["handoff"]["invariants"]["independent_readback_verified"]
        self.assertEqual(project(payload)["steps"]["readback"],"not_established")

    def test_capture_digest_can_wrap_on_mobile(self):
        css=(ROOT/"ui"/"styles.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.proof-caveat\s*\{[^}]*overflow-wrap\s*:\s*anywhere")

    def test_inspector_keeps_block_flow_in_integrated_views(self):
        css=(ROOT/"ui"/"styles.css").read_text(encoding="utf-8")
        self.assertRegex(css, r'\.workspace\[data-section="scenarios"\] \.inspector,\s*'
                         r'\.workspace\[data-section="conversation"\] \.inspector\s*\{display:block\}')
        self.assertRegex(css, r'\.facts-list>div,\.detail-list>div\s*\{display:grid')
        self.assertNotRegex(css, r'\.inspector\s*\{[^}]*display:flex')
        # Production-DOM checks independently measure two-column geometry
        # and no page overflow at wide/intermediate/mobile viewports.

    def test_false_or_contradictory_never_passes(self):
        payload=self.copy()
        payload["summary"]["handoff"]["invariants"]["target_bytes_match_processor_output"]=False
        self.assertEqual(project(payload)["steps"]["replication"],"contradicted")
        payload=self.copy()
        payload["summary"]["handoff"]["replication"]["target_sha256"]="f"*64
        self.assertEqual(project(payload)["steps"]["replication"],"contradicted")
        payload=self.copy()
        payload["summary"]["handoff"]["replication"]["target_byte_size"]=676
        self.assertEqual(project(payload)["steps"]["replication"],"contradicted")
        payload=self.copy()
        payload["summary"]["handoff"]["replication"]["replay"]["published"]=1
        self.assertEqual(project(payload)["steps"]["replay"],"contradicted")
        payload=self.copy()
        payload["summary"]["handoff"]["replication"]["verification"]["verified"]=0
        self.assertEqual(project(payload)["steps"]["readback"],"contradicted")

    def test_malformed_counters_and_schema(self):
        payload=self.copy()
        payload["summary"]["handoff"]["replication"]["first_run"]["published"]="1"
        self.assertEqual(project(payload)["steps"]["replication"],"contradicted")
        payload=self.copy()
        payload["summary"]["handoff"]["schema_version"]=9
        self.assertEqual(project(payload)["overall"],"contradicted")
        payload=self.copy()
        del payload["summary"]["handoff"]["replication"]["target_sha256"]
        self.assertEqual(project(payload)["steps"]["replication"],"not_established")

    def test_snapshot_integrity_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            dest=Path(td)
            (dest/"showcase-response.json").write_bytes(b'{"cached":false}')
            (dest/"provenance.json").write_text(json.dumps(self.data["provenance"]),encoding="utf-8")
            with self.assertRaises(ProofUnavailable):
                load_snapshot(dest)
            (dest/"showcase-response.json").write_bytes((ROOT/"proof"/"showcase-response.json").read_bytes())
            self.assertEqual(load_snapshot(dest)["projection"]["overall"],"supported")
            (dest/"showcase-response.json").write_text('INVALID',encoding="utf-8")
            with self.assertRaises(ProofUnavailable):
                load_snapshot(dest)

    def test_proof_is_read_only_and_never_model_context(self):
        mock=MockTransport(delay=0)
        svc=PanelSupervisor(transport=mock)
        with TestClient(create_app(svc,port=8765),base_url="http://127.0.0.1:8765") as client:
            response=client.get("/api/proof")
            self.assertEqual(response.status_code,200)
            data=response.json()
            self.assertTrue(data["snapshot"]["cached"])
            self.assertEqual(data["projection"]["steps"]["replay"],"supported")
            self.assertEqual(mock.calls,0)
            self.assertNotIn("handoff",client.get("/api/facts/prepared").json()["facts"])
            self.assertNotIn("proof",client.get("/api/facts/prepared").json()["facts"])
            self.assertEqual(mock.calls,0)
            self.assertEqual(client.post("/api/proof",headers={"Origin":"http://127.0.0.1:8765"}).status_code,405)
            self.assertEqual(client.get("/proof.js").status_code,200)
            self.assertEqual(mock.calls,0)


if __name__=="__main__":
    unittest.main()
