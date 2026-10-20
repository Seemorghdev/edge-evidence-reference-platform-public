"""One active read-only local turn. The real transport owns only port 11435.

Explicit fake transports are injected in tests; never selected as a fallback.
No processes or listeners are started by importing this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from boundaries import MODEL, DIGEST, PORT, SafetyViolation, HttpGate, verify_source
from explanation_policy import make_presentation, check_explanation
from run_case import (check_revision, child_environment, load_baseline, make_report,
                      port_free, preflight, stop_owned, verified_port_release, version_check)

ROOT = Path(__file__).resolve().parent.parent
MAX_HISTORY = 20
MAX_EVENTS = 64

def observed_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

FIXTURE_FILES = {
    "complete": ("Recorded complete", "artifact-complete.json"),
    "deferred": ("Bounded defer", "artifact-deferred.json"),
    "prepared": ("Prepared, awaiting catch-up", "artifact-prepared.json"),
}


class ModelUnavailable(Exception):
    pass


@dataclass
class Turn:
    id: str
    cancel: threading.Event
    # The optional callback receives only allowlisted observation snapshots.
    observe: object = None
    streaming: bool = False


def public_facts(baseline: dict) -> dict:
    """Whitelisted deterministic fields only; no model-provided values."""
    return {key: baseline[key] for key in (
        "artifact_id", "classification", "requires_human_approval", "mutation_authorized")}


def matches_facts(result, known) -> bool:
    """JSON numeric lookalikes must not pass authorization-boolean checks."""
    return isinstance(result, dict) and isinstance(known, dict) and (
        result.get('artifact_id') == known['artifact_id'] and
        result.get('classification') == known['classification'] and
        result.get('requires_human_approval') is known['requires_human_approval'] and
        result.get('mutation_authorized') is known['mutation_authorized'])


def public_result(report: dict, *, fixture_id: str, mock: bool = False) -> dict:
    view = make_presentation(report)
    status = report.get("status")
    if status == "RESPONSE_OBSERVED":
        state = "completed" if view["display_origin"] == "MODEL_EXPLANATION" else "output_withheld"
    else:
        state = {
            "SCHEMA_REJECTED": "invalid_record", "SAFETY_REJECTED": "request_blocked",
            "TIMEOUT_OBSERVED": "timeout", "CANCELLED": "cancelled",
            "MODEL_UNAVAILABLE": "model_unavailable", "HARNESS_ERROR": "harness_error",
        }.get(status, "harness_error")
    return {
        "fixture_id": fixture_id, "state": state, "facts": view["authoritative_facts"],
        "facts_origin": view["facts_origin"], "limits": view["deterministic_boundaries"],
        "explanation": view["display_text"], "display_origin": view["display_origin"],
        "raw_model_answer": view["raw_model_answer"],
        "guard_reasons": view["output_policy"]["reasons"],
        "guard_limitation": view["output_policy"]["limitation"],
        "request_count": len(report.get("model_requests", [])),
        "tool_count": len(report.get("tool_attempts", [])),
        "elapsed_seconds": report.get("timing", {}).get("turn_elapsed_seconds"),
        "mock_transport": mock,
        "http_metrics": [{k:v for k,v in item.items() if k in (
            'wall_seconds','first_chunk_wall_seconds','total_duration','load_duration',
            'prompt_eval_count','prompt_eval_duration','eval_count','eval_duration') and
            type(v) in (int,float) and 0<=v<=120_000_000_000}
            for item in report.get('http_timings',[])[:2] if isinstance(item,dict)],
        "cleanup_observation": deepcopy(report.get("_cleanup_observation", {})),
        "error_type": report.get("error", {}).get("type") if isinstance(report.get("error"), dict) else None,
    }


class _NoRedirect(__import__('urllib.request',fromlist=['HTTPRedirectHandler']).HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise SafetyViolation('Preload redirect refused')


class RealTransport:
    """Long-lived owned local server; one fresh isolated SDK worker per turn."""
    def __init__(self, source: Path, ollama_bin: Path | None = None, model_store: Path | None = None):
        self.source = source
        self.binary = ollama_bin
        self.store = model_store
        self.server = None
        self.server_log = None
        self.server_home = None
        self._lock = threading.RLock()
        self.poisoned = False
        self.preflight_verified = False
        self._warming = False
        self._busy = False
        self._warmed = False
        self._warm_error = None
        self._warm_observed = None
        self._idle_timer = None
        self._expiry = None
        self._generation = 0
        self._warm_idle=threading.Event();self._warm_idle.set()

    def readiness(self) -> dict:
        with self._lock:
            if self.poisoned: state='cleanup_blocked'
            elif self._busy: state='busy'
            elif self._warming: state='warming'
            elif self._warmed and self.server is not None and self.server.poll() is None and (
                    self._expiry is None or time.monotonic()<self._expiry): state='ready'
            elif self._warm_error: state='unavailable'
            else: state='cold' if self._warm_observed is not None else 'starting'
            return {'state':state,'model':MODEL,'interactive_idle_seconds':600,
                    'warmup_observed_seconds':self._warm_observed,
                    'note':'Ready means pinned preload completed on this owned server; not a guarantee of future inference.'}

    def _cancel_idle(self):
        self._generation+=1
        if self._idle_timer is not None:
            self._idle_timer.cancel();self._idle_timer=None

    def _idle_unload(self, generation):
        with self._lock:
            if generation!=self._generation or self._busy or self._warming or self.poisoned:return
            # Shutdown the ONLY owned experimental service, never an unknown listener.
            self._stop_server()
            self._warmed=False;self._expiry=None

    def _schedule_idle(self):
        self._cancel_idle()
        if self.server is not None and not self.poisoned:
            self._expiry=time.monotonic()+600
            timer=threading.Timer(600,self._idle_unload,args=(self._generation,))
            timer.daemon=True;self._idle_timer=timer;timer.start()

    def prepare(self) -> dict:
        # Supervisor serializes this with turns; one bounded preload per preparation.
        with self._lock:
            if self.poisoned: return self.readiness()
            if self._busy or self._warming: return self.readiness()
            if self._warmed and self.server is not None and self.server.poll() is None:
                return self.readiness()
            self._warming=True;self._warm_idle.clear();self._warm_error=None;self._cancel_idle()
        started=time.monotonic()
        try:
            version_check()
            self._ensure_server(make_report('panel')) # checks 11435 ownership, installed digest and version
            from urllib import request
            payload={'model':MODEL,'prompt':'','stream':False,'keep_alive':600}
            HttpGate('warm').validate('POST',f'http://127.0.0.1:{PORT}/api/generate',payload)
            req=request.Request(f'http://127.0.0.1:{PORT}/api/generate',
                data=json.dumps(payload).encode('utf-8'),headers={'Content-Type':'application/json'},method='POST')
            # Network read and time are bounded; no model download, no question/tool.
            # Never inherit an owner/system HTTP proxy for this loopback-only call.
            with request.build_opener(request.ProxyHandler({}),_NoRedirect()).open(req,timeout=20) as response:
                body=response.read(4097)
                if response.status!=200 or len(body)>4096:
                    raise ModelUnavailable('Warm preload returned an invalid response')
                loaded=json.loads(body)
                if (type(loaded) is not dict or loaded.get('model') != MODEL or
                        loaded.get('done') is not True or 'error' in loaded):
                    raise ModelUnavailable('Pinned preload completion was not observed')
            with self._lock:
                self._warmed=True;self._warm_observed=round(time.monotonic()-started,3)
        except Exception:
            with self._lock:
                self._warmed=False;self._warm_error='Pinned model setup or preload unavailable'
                self._stop_server()
        finally:
            with self._lock:
                self._warming=False
                if self._warmed:self._schedule_idle()
                self._warm_idle.set()
        return self.readiness()

    def _stop_server(self) -> bool:
        with self._lock:
            self._cancel_idle()
            self._warmed=False;self._expiry=None
            if self.server is None:
                return True
            stopped = stop_owned(self.server, seconds=3)
            released = verified_port_release(seconds=3)
            self.server = None
            self.preflight_verified = False
            if self.server_log is not None:
                self.server_log.close()
                self.server_log = None
            if self.server_home is not None:
                self.server_home.cleanup()
                self.server_home = None
            if not (stopped and released):
                self.poisoned = True
                return False
            return True

    def close(self) -> bool:
        # A preload request may still be reading; never claim shutdown while it runs.
        if not self._warm_idle.wait(35):
            self.poisoned=True
            return False
        return self._stop_server()

    def _ensure_server(self, report: dict) -> None:
        with self._lock:
            if self.poisoned:
                raise SafetyViolation("Owned process cleanup could not be verified")
            if self.server is not None:
                if self.server.poll() is not None:
                    self._stop_server()
                    raise ModelUnavailable("Experimental Ollama server exited")
                if not self.preflight_verified:
                    raise SafetyViolation("Experimental server not verified")
                return
            # Never attach to an unknown service or touch the owner's 11434.
            if not port_free():
                raise SafetyViolation("Experimental port 11435 is already occupied")
            if self.binary is None or not self.binary.is_file() or not os.access(self.binary, os.X_OK):
                raise ModelUnavailable("Explicit installed Ollama executable unavailable")
            if self.store is None or not self.store.is_dir():
                raise ModelUnavailable("Explicit local model store unavailable")
            self.server_home = tempfile.TemporaryDirectory(prefix="edge-panel-server-")
            self.server_log = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
            env = child_environment(self.server_home.name, self.source)
            env.update({"OLLAMA_HOST": f"127.0.0.1:{PORT}", "OLLAMA_MODELS": str(self.store.resolve())})
            self.server = subprocess.Popen([str(self.binary.resolve()), "serve"], env=env,
                stdin=subprocess.DEVNULL, stdout=self.server_log, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True)
            try:
                preflight(self.server, self.server_log, report)
                self.preflight_verified = True
            except Exception:
                if not self._stop_server():
                    raise SafetyViolation("Experimental server cleanup unverified")
                raise

    def run(self, report: dict, fixture: dict, question: str, turn: Turn) -> None:
        with self._lock:
            if self._warming or self._busy:raise SafetyViolation('Interactive server busy')
            self._busy=True;self._cancel_idle()
            if not turn.streaming:self._warmed=False
        worker = None
        timed_out = False
        cleanup = {"worker": "NOT_STARTED", "server": "NOT_OBSERVED",
                   "port_released": None, "mock_transport": False}
        report["_cleanup_observation"] = cleanup
        with tempfile.TemporaryDirectory(prefix="edge-panel-turn-") as home:
            try:
                if turn.cancel.is_set():
                    report["status"] = "CANCELLED"
                    return
                version_check()
                self._ensure_server(report)
                cleanup["server"] = "RETAINED"
                if turn.cancel.is_set():
                    report["status"] = "CANCELLED"
                    return
                config = Path(home) / "input.json"
                trace = Path(home) / "observations.json"
                config.write_text(json.dumps({"fixture": fixture, "baseline": report["baseline"],
                    "prompt": question, "keep_alive_seconds": 600 if turn.streaming else 120,
                    "interactive_stream": turn.streaming}, ensure_ascii=False), encoding="utf-8")
                worker = subprocess.Popen([sys.executable, "-B", str(Path(__file__).with_name("runtime_worker.py")),
                     str(config), str(trace)], env=child_environment(home, self.source),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, close_fds=True)
                cleanup["worker"] = "RUNNING"
                deadline = time.monotonic() + 30
                last_snapshot = None
                while worker.poll() is None:
                    if trace.is_file() and turn.observe is not None:
                        try:
                            snapshot = json.loads(trace.read_text(encoding="utf-8"))
                            if snapshot != last_snapshot:
                                turn.observe(snapshot)
                                last_snapshot = snapshot
                        except (OSError, ValueError):
                            pass  # Worker atomically replaces its snapshots.
                    if turn.cancel.is_set():
                        report["status"] = "CANCELLED"
                        break
                    if time.monotonic() >= deadline:
                        report["status"] = "TIMEOUT_OBSERVED"
                        report["error"] = {"type": "TurnDeadline", "message": "30-second turn deadline reached"}
                        timed_out = True
                        break
                    time.sleep(0.05)
                worker_stopped = stop_owned(worker)
                cleanup["worker"] = "VERIFIED_STOPPED" if worker_stopped is True else "UNVERIFIED"
                if worker_stopped is not True:
                    self.poisoned = True
                    raise SafetyViolation("Worker cleanup unverified")
                if trace.is_file():
                    state = json.loads(trace.read_text(encoding="utf-8"))
                    if turn.observe is not None:
                        turn.observe(state)
                    for key in ("model_requests", "tool_attempts", "answer", "http_timings"):
                        report[key] = state.get(key, report.get(key))
                    if report["status"] not in ("TIMEOUT_OBSERVED", "CANCELLED"):
                        report["status"] = state.get("status", "HARNESS_ERROR")
                        report["error"] = state.get("error")
                elif report["status"] not in ("TIMEOUT_OBSERVED", "CANCELLED"):
                    report["status"] = "HARNESS_ERROR"
                    report["error"] = {"type": "MissingWorkerObservation"}
            except (ModelUnavailable, importlib.metadata.PackageNotFoundError):
                report["status"] = "MODEL_UNAVAILABLE"
            except SafetyViolation:
                report["status"] = "HARNESS_ERROR"
                report["error"] = {"type": "SafetyOrSetupBoundary"}
            except Exception:
                report["status"] = "HARNESS_ERROR"
                report["error"] = {"type": "LocalWorkerOrModelSetup"}
            finally:
                if worker is not None and worker.poll() is None:
                    worker_stopped = stop_owned(worker)
                    cleanup["worker"] = "VERIFIED_STOPPED" if worker_stopped is True else "UNVERIFIED"
                    if not worker_stopped:
                        self.poisoned = True
                # Killing the worker alone cannot prove an in-flight model generation stopped.
                if timed_out or turn.cancel.is_set() or self.poisoned:
                    had_server = self.server is not None
                    server_stopped = self._stop_server()
                    if had_server:
                        cleanup["server"] = "VERIFIED_STOPPED" if server_stopped else "UNVERIFIED"
                        cleanup["port_released"] = True if server_stopped else None
                    if not server_stopped:
                        self.poisoned = True
                if self.poisoned:
                    report["status"] = "HARNESS_ERROR"
                    report["error"] = {"type": "CleanupUnverified"}
                with self._lock:
                    self._busy=False
                    if self.server is not None and not self.poisoned:self._schedule_idle()


class MockTransport:
    """An EXPLICIT test-only stand-in, not a fallback for model failures."""
    mock = True
    def __init__(self, outcome: str = "completed", delay: float = .25):
        self.outcome = outcome
        self.delay = delay
        self.calls = 0

    def close(self):
        return True

    def run(self, report: dict, fixture: dict, question: str, turn: Turn):
        # Explicit test simulation, never evidence of real process cleanup.
        report["_cleanup_observation"] = {"worker": "VERIFIED_STOPPED",
            "server": "NOT_OBSERVED", "port_released": None, "mock_transport": True}
        self.calls += 1
        started = time.monotonic()
        while time.monotonic() - started < self.delay:
            if turn.cancel.is_set():
                report["status"] = "CANCELLED"
                return
            time.sleep(.01)
        kind = self.outcome
        report["model_requests"] = [{"mock": True}]
        report["tool_attempts"] = ([{"allowed": True, "name": "inspect_selected_artifact", "arguments": {},
                                     "result": deepcopy(report["baseline"])}] if kind in ("completed", "withheld") else [])
        if turn.observe is not None:
            turn.observe({"model_requests": report["model_requests"],
                "http_timings": [{"status_code": 200, "metrics_unavailable": True}] if kind in ("completed", "withheld") else [],
                "tool_attempts": report["tool_attempts"], "blocked_attempts": []})
        report["status"] = {"completed": "RESPONSE_OBSERVED", "withheld": "RESPONSE_OBSERVED",
                            "blocked": "SAFETY_REJECTED", "timeout": "TIMEOUT_OBSERVED",
                            "unavailable": "MODEL_UNAVAILABLE", "invalid": "SCHEMA_REJECTED",
                            "error": "HARNESS_ERROR"}.get(kind, "HARNESS_ERROR")
        if kind == "completed":
            # Not generated by any model: clearly identified as mocked transport in UI.
            report["answer"] = json.dumps({"explanation": (
                "This synthetic record has a recorded finished state." if fixture["state"] == "complete"
                else "This synthetic record is waiting. A completed result is not recorded.")})
        if kind == "withheld":
            report["answer"] = json.dumps({"explanation": "Run sudo --do-work to verify copies."})


class PanelSupervisor:
    def __init__(self, root: Path = ROOT, transport=None, source: Path | None = None,
                 manifest: Path | None = None, ollama_bin: Path | None = None, model_store: Path | None = None):
        self.root = Path(root)
        self.source = Path(source) if source is not None else Path(os.getenv("EDGE_EVIDENCE_PUBLIC_SOURCE", self.root / "public-source"))
        self.manifest = Path(manifest) if manifest is not None else Path(os.getenv("EDGE_EVIDENCE_SOURCE_MANIFEST", self.root / "SOURCE-MANIFEST.json"))
        self.transport = transport if transport is not None else RealTransport(self.source, ollama_bin, model_store)
        self._lock = threading.RLock()
        self._active: Turn | None = None
        self._idle = threading.Event()
        self._idle.set()
        self._unsafe = False
        self._turns = OrderedDict()  # Bounded, memory-only, not browser persistence.
        self._preparing = False
        self._prepare_state = 'starting'

    def readiness(self) -> dict:
        with self._lock:
            if self._unsafe: return {'state':'cleanup_blocked'}
            if self._active is not None: return {'state':'busy'}
            if self._preparing:return {'state':'warming'}
        if hasattr(self.transport,'readiness'):return self.transport.readiness()
        return {'state':'mock' if getattr(self.transport,'mock',False) else 'unavailable',
                'mock_transport':bool(getattr(self.transport,'mock',False))}

    def prepare(self) -> dict:
        with self._lock:
            if self._unsafe:return {'state':'cleanup_blocked'}
            if self._active is not None or self._preparing:return self.readiness()
            self._preparing=True
        try:
            if hasattr(self.transport,'prepare'):return self.transport.prepare()
            return self.readiness()
        finally:
            with self._lock:self._preparing=False

    def start_prepare_once(self):
        with self._lock:
            if getattr(self,'_prepare_started',False):return
            self._prepare_started=True
        threading.Thread(target=self.prepare,daemon=True,name='edge-evidence-preload').start()


    def _fixture(self, fixture_id: str):
        if fixture_id not in FIXTURE_FILES:
            raise ValueError("Unknown synthetic fixture")
        check_revision(self.source, self.manifest)
        verify_source(self.source, self.manifest)
        record = json.loads((self.source / "fixtures" / FIXTURE_FILES[fixture_id][1]).read_text(encoding="utf-8"))
        baseline = load_baseline(self.source, record)
        return record, baseline

    def facts(self, fixture_id: str) -> dict:
        record, baseline = self._fixture(fixture_id)
        return {"fixture_id": fixture_id, "label": FIXTURE_FILES[fixture_id][0],
                "facts": public_facts(baseline), "record": {k: deepcopy(record[k]) for k in
                    ("artifact_id", "state", "source", "created_at", "snapshot_eligible", "labels", "digest")},
                "synthetic": True,
                "model": MODEL, "model_digest": DIGEST, "mock_transport": bool(getattr(self.transport, "mock", False)),
                "limits": {"action_tools_available": False,
                           "independent_readback": "NOT_ESTABLISHED_BY_THIS_INSPECTION",
                           "scope_note": "Only this supplied synthetic record was inspected; no independent readback is shown."}}

    def _reserve(self, fixture_id: str, question: str, streaming: bool = False) -> Turn:
        if (fixture_id not in FIXTURE_FILES or type(question) is not str or
            not question.strip() or len(question) > 2000 or "\x00" in question):
            raise ValueError("Invalid fixture or question")
        with self._lock:
            if self._active is not None or self._unsafe or self._preparing:
                raise RuntimeError("An inference is active or prior cleanup is unverified")
            turn = Turn(uuid.uuid4().hex, threading.Event(),streaming=streaming)
            self._active = turn
            self._idle.clear()
            self._turns[turn.id] = {
                "turn_id": turn.id, "fixture_id": fixture_id, "question": question,
                "status": "pending", "result": None, "facts_snapshot": None,
                "record_snapshot": None, "events": [], "started_at": observed_now(),
                "elapsed_seconds": None, "stream": {"phase":"waiting","text":"","seq":0},
                "revision": 0, "_indices": {"stream_chunks": 0,"model_requests": 0,
                    "http_timings": 0, "tool_attempts": 0, "blocked_attempts": 0},
                "_began": time.monotonic(), "_next_event": 0,
            }
            while len(self._turns) > MAX_HISTORY:
                self._turns.popitem(last=False)
            self._emit_locked(turn.id, "turn_accepted", {"fixture_id": fixture_id})
            return turn

    def _emit_locked(self, turn_id: str, kind: str, data: dict):
        row = self._turns.get(turn_id)
        if row is None:
            return
        events = row["events"]
        row["_next_event"] += 1
        events.append({"id": f"{turn_id}:{row['_next_event']}", "turn_id": turn_id,
            "type": kind, "observed_at": observed_now(), "data": data})
        row['revision']+=1
        if len(events) > MAX_EVENTS:
            del events[:len(events)-MAX_EVENTS]

    def _observations(self, turn_id: str, snapshot: dict):
        # Snapshot timestamps are receipt times, not claimed operation start times.
        # Accept only counts and literal safe fields, never SDK event dictionaries,
        # stack/error text, paths, environment, prompt, or arbitrary tool arguments.
        with self._lock:
            row = self._turns.get(turn_id)
            if row is None:
                return
            indices = row["_indices"]
            # Separate bounded explanation projection: no event timeline eviction.
            chunks=snapshot.get('stream_chunks',[])
            if isinstance(chunks,list):
                for position,item in enumerate(chunks[indices['stream_chunks']:256],indices['stream_chunks']+1):
                    indices['stream_chunks']=position
                    if not isinstance(item,dict) or item.get('seq')!=position or item.get('phase')!='explanation':continue
                    accepted=any(ev['type']=='tool_attempt_observed' and ev['data'].get('accepted_result') is True for ev in row['events'])
                    # Stream delivery can be ahead of the tool-event projection in this same snapshot.
                    if not accepted:
                        attempts=snapshot.get('tool_attempts',[])
                        if not isinstance(attempts,list):attempts=[]
                        accepted=any(isinstance(x,dict) and x.get('allowed') is True and
                            x.get('name')=='inspect_selected_artifact' and isinstance(x.get('result'),dict) and
                            matches_facts(x['result'],row['facts_snapshot']) for x in attempts[:2])
                    delta=item.get('delta')
                    requests=snapshot.get('model_requests',[])
                    if not accepted or not isinstance(requests,list) or len(requests)<2 or type(delta) is not str or not delta or len(delta)>1200:continue
                    combined=row['stream']['text']+delta
                    if len(combined)>1200 or not check_explanation(json.dumps({'explanation':combined}),row['facts_snapshot']['classification'])['accepted_for_display']:
                        row['stream']['phase']='stopped';row['revision']+=1;break
                    row['stream']={'phase':'draft','text':combined,'seq':position}
                    row['revision']+=1
            for key, event in (("model_requests", "model_request_allowed"),
                               ("http_timings", "http_response_observed"),
                               ("tool_attempts", "tool_attempt_observed"),
                               ("blocked_attempts", "boundary_refusal_observed")):
                items = snapshot.get(key, [])
                if not isinstance(items, list):
                    continue
                # Clamp untrusted child data to the known worker budgets.
                cap = {"model_requests": 2, "http_timings": 2,
                       "tool_attempts": 2, "blocked_attempts": 8}[key]
                for position, item in enumerate(items[indices[key]:cap], indices[key] + 1):
                    indices[key] = position
                    if not isinstance(item, dict):
                        continue
                    data = {"observation_index": position,
                            "mock_transport": bool(getattr(self.transport, "mock", False))}
                    if key == "http_timings":
                        code = item.get("status_code")
                        if type(code) is int and 100 <= code <= 599:
                            data["status_code"] = code
                        seconds = item.get("wall_seconds")
                        if type(seconds) in (int, float) and 0 <= seconds <= 120:
                            data["response_wall_seconds"] = round(seconds, 3)
                        data["metrics_available"] = any(k in item for k in
                            ("total_duration", "load_duration", "prompt_eval_count", "eval_count", "eval_duration"))
                        data['metrics']={k:round(item[k],4) for k in (
                            'first_chunk_wall_seconds','total_duration','load_duration',
                            'prompt_eval_count','prompt_eval_duration','eval_count','eval_duration')
                            if type(item.get(k)) in (int,float) and 0<=item[k]<=120_000_000_000}
                    if key == "tool_attempts":
                        data["tool"] = ("inspect_selected_artifact" if item.get("name") == "inspect_selected_artifact"
                                        else "unrecognized_tool")
                        data["fixture_id"] = row["fixture_id"]
                        result = item.get("result")
                        known = row["facts_snapshot"]
                        matches = matches_facts(result, known)
                        data["accepted_result"] = (item.get("allowed") is True and matches and
                            item.get("name") == "inspect_selected_artifact")
                        if not data["accepted_result"]:
                            data["outcome"] = "refused_or_failed"
                    if key == "blocked_attempts":
                        data["boundary"] = "transport_or_worker"
                    self._emit_locked(turn_id, event, data)
                # If a snapshot was malformed, later snapshots may still be usable.

    def _execute(self, turn: Turn, fixture_id: str, question: str) -> dict:
        started = time.monotonic()
        report = make_report("panel")
        mock = bool(getattr(self.transport, "mock", False))
        try:
            try:
                record, baseline = self._fixture(fixture_id)
                report["baseline"] = baseline
                with self._lock:
                    row = self._turns[turn.id]
                    row["facts_snapshot"] = public_facts(baseline)
                    row["record_snapshot"] = {k: deepcopy(record[k]) for k in
                        ("artifact_id", "state", "source", "created_at", "snapshot_eligible", "labels", "digest")}
            except Exception:
                report["status"] = "HARNESS_ERROR"
                report["error"] = {"type": "PinnedSourceOrInspectorUnavailable"}
            else:
                if turn.cancel.is_set():
                    report["status"] = "CANCELLED"
                else:
                    turn.observe = lambda state: self._observations(turn.id, state)
                    self.transport.run(report, record, question, turn)
                if turn.cancel.is_set() and report["status"] != "HARNESS_ERROR":
                    report["status"] = "CANCELLED"
                try:
                    if verify_source(self.source, self.manifest) is None:
                        raise ValueError("Source unverified")
                except Exception:
                    report["status"] = "HARNESS_ERROR"
                    report["error"] = {"type": "SourceChanged"}
            report["timing"]["turn_elapsed_seconds"] = round(time.monotonic()-started, 3)
            return public_result(report, fixture_id=fixture_id, mock=mock)
        except Exception:
            report["status"] = "HARNESS_ERROR"
            report["error"] = {"type": "LocalSupervisorError"}
            report["timing"]["turn_elapsed_seconds"] = round(time.monotonic()-started, 3)
            return public_result(report, fixture_id=fixture_id, mock=mock)
        finally:
            with self._lock:
                self._unsafe = self._unsafe or bool(getattr(self.transport, "poisoned", False))
                # The actual turn remains reserved until result publication/cleanup.

    def _finish(self, turn: Turn, fixture_id: str, question: str):
        result = self._execute(turn, fixture_id, question)
        with self._lock:
            row = self._turns[turn.id]
            row["result"] = result
            row["status"] = "finished"
            # A terminal response never keeps an unapproved draft in the answer surface.
            row['stream']={'phase':'final' if result['state']=='completed' else 'removed',
                           'text':'','seq':row['stream']['seq']}
            row['revision']+=1
            row["elapsed_seconds"] = result["elapsed_seconds"]
            self._emit_locked(turn.id, "presentation_checked", {
                "state": result["state"], "display_origin": result["display_origin"],
                "guard_reasons": result["guard_reasons"][:12]})
            cleanup = result.get("cleanup_observation", {})
            if self._unsafe:
                self._emit_locked(turn.id, "cleanup_unverified", {"mock_transport": bool(getattr(self.transport, "mock", False))})
            elif cleanup.get("worker") == "VERIFIED_STOPPED" or cleanup.get("server") == "VERIFIED_STOPPED":
                self._emit_locked(turn.id, "owned_cleanup_verified", cleanup)
            else:
                self._emit_locked(turn.id, "turn_slot_released", {
                    "mock_transport": bool(getattr(self.transport, "mock", False)),
                    "note": "No owned-process cleanup observation was recorded; do not infer a worker ran."})
            self._active = None
            self._idle.set()
        return result

    def ask(self, fixture_id: str, question: str) -> dict:
        # Legacy synchronous API stays compatible with the original case/panel tests.
        turn = self._reserve(fixture_id, question)
        return self._finish(turn, fixture_id, question)

    def start(self, fixture_id: str, question: str) -> str:
        turn = self._reserve(fixture_id, question, streaming=True)
        thread = threading.Thread(target=self._finish, args=(turn,fixture_id,question),
                                  name="edge-evidence-turn", daemon=True)
        thread.start()
        return turn.id

    def get_turn(self, turn_id: str) -> dict | None:
        with self._lock:
            row = self._turns.get(turn_id)
            if row is None:
                return None
            return {k: deepcopy(v) for k, v in row.items() if not k.startswith("_")}

    def cancel(self, turn_id: str | None = None) -> bool:
        with self._lock:
            if self._active is None or (turn_id is not None and self._active.id != turn_id):
                return False
            if not self._active.cancel.is_set():
                self._active.cancel.set()
                self._emit_locked(self._active.id, "cancel_requested", {})
            return True

    def clear_history(self) -> bool:
        with self._lock:
            if self._active is not None or self._unsafe:
                return False
            self._turns.clear()
            return True

    def close(self) -> bool:
        self.cancel()
        if not self._idle.wait(timeout=9):
            self._unsafe = True
            return False
        safe = self.transport.close()
        self._unsafe = self._unsafe or not safe
        return not self._unsafe
