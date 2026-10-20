"""One short-lived, supervised ADK inference turn. Not an OS sandbox.

The supervisor starts this file with an allowlisted, credential-free environment and
terminates its owned process group on timeout. Importing the module has no effects.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import sys
import time
from datetime import datetime, timezone

from boundaries import (CONTEXT, MAX_REQUESTS, MAX_TOKENS, MODEL, PORT, HttpGate,
                        SelectedFixtureTool, SafetyViolation, require_local_address)
from explanation_policy import (explanation_view, MODEL_INSTRUCTION,
                                INTERACTIVE_INSTRUCTION, INSPECTION_REQUEST, prepare_final_request)
from stream_projection import DraftProjector


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_snapshot(path: Path, data: dict) -> None:
    # Crash-tolerant, one-writer snapshots, confined to new output directory.
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False, default=str), encoding="utf-8")
    temp.replace(path)


def sanitize_event(event) -> dict:
    # Model data only; no Python reprs or exception text from local stack traces.
    value = event.model_dump(mode="json", exclude_none=True)
    return value


async def run(config: dict, path: Path) -> dict:
    state = {"status": "HARNESS_ERROR", "model_requests": [], "events": [],
             "tool_attempts": [], "answer": None, "usage": [], "blocked_attempts": [],
             "unexpected_connections": [], "error": None, "started_at_utc": utc(),
             "finished_at_utc": None, "http_timings": [], "stream_chunks": []}
    keep_alive_seconds=config.get("keep_alive_seconds",0)
    streaming=config.get("interactive_stream", False) is True
    projector=DraftProjector(config["baseline"].get("classification"))
    last_draft_snapshot=0.0
    gate = HttpGate("turn",keep_alive_seconds=keep_alive_seconds,allow_stream=streaming)
    selected_tool = None

    def snapshot():
        state["model_requests"] = deepcopy(gate.accepted)
        state["blocked_attempts"] = deepcopy(gate.blocked) + state.get("network_blocked", [])
        state["tool_attempts"] = deepcopy(selected_tool.calls) if selected_tool is not None else []
        write_snapshot(path, {k: v for k, v in state.items() if k != "network_blocked"})

    def audit(event, args):
        if event == "socket.connect":
            try:
                require_local_address(args[1], PORT)
            except (SafetyViolation, IndexError):
                state.setdefault("network_blocked", []).append({"kind": "socket", "reason": "Blocked non-dedicated network connection"})
                raise SafetyViolation("Non-loopback/dedicated socket blocked")
        elif event == "socket.getaddrinfo":
            if not args or args[0] not in ("127.0.0.1", b"127.0.0.1"):
                state.setdefault("network_blocked", []).append({"kind": "dns", "reason": "External DNS blocked"})
                raise SafetyViolation("External DNS blocked")
        elif event in ("subprocess.Popen", "os.system", "os.posix_spawn", "socket.bind", "socket.listen"):
            state.setdefault("network_blocked", []).append({"kind": "process-or-listener", "reason": "Worker subprocess/listener blocked"})
            raise SafetyViolation("Worker process creation/listener blocked")

    try:
        # Trust none of the inherited SDK environment; this child is given a fresh
        # whitelist by its parent. No dotenv loading may precede this audit hook.
        sys.addaudithook(audit)
        import httpx
        from edge_evidence_edge_agent.adk_adapter import inspect_artifact_tool
        from google.adk import Agent
        from google.adk.models.lite_llm import LiteLlm
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.adk.agents.run_config import RunConfig
        from google.genai import types
        import litellm

        litellm.telemetry = False
        litellm.set_verbose = False
        litellm.drop_params = False
        selected_tool = SelectedFixtureTool(config["fixture"], config["baseline"], inspect_artifact_tool)

        async_send = httpx.AsyncClient.send
        sync_send = httpx.Client.send

        def check_request(request, kwargs):
            if kwargs.get("follow_redirects") is True:
                raise SafetyViolation("Redirect following refused")
            if request.content:
                try:
                    payload = json.loads(request.content)
                except (ValueError, UnicodeDecodeError) as exc:
                    gate.blocked.append({"kind": "http", "reason": "Non-JSON request payload"})
                    raise SafetyViolation("Malformed HTTP JSON") from None
            else:
                payload = None
            if request.method=="POST" and request.url.path=="/api/chat" and type(payload) is dict:
                prepared=prepare_final_request(payload, question=config['prompt'] if streaming else None)
                if prepared!=payload:
                    headers={k:v for k,v in request.headers.items() if k.lower()!="content-length"}
                    request=httpx.Request(request.method, request.url, headers=headers,
                                          json=prepared, extensions=request.extensions)
                    payload=prepared
            gate.validate(request.method, str(request.url), payload)
            snapshot()
            return request

        async def guarded_async(client, request, *args, **kwargs):
            request=check_request(request, kwargs)
            wire_stream=json.loads(request.content).get("stream") is True
            started=time.monotonic()
            response = await async_send(client, request, *args, follow_redirects=False, **{k: v for k, v in kwargs.items() if k != "follow_redirects"})
            if response.is_redirect:
                gate.blocked.append({"kind": "redirect", "reason": "Redirect response refused"})
                raise SafetyViolation("Redirect response refused")
            if wire_stream:
                # Tee bytes as the SDK consumes them. Never pre-read/buffer the response.
                original_raw=response.aiter_raw
                async def measured_raw(*a, **kw):
                    line_buffer=b''; metrics={}; received=False; first_chunk=None
                    try:
                        async for block in original_raw(*a, **kw):
                            if first_chunk is None:first_chunk=round(time.monotonic()-started,6)
                            received=True
                            line_buffer=(line_buffer+block)[-8192:]
                            while b'\n' in line_buffer:
                                line,line_buffer=line_buffer.split(b'\n',1)
                                if len(line)>4096: continue
                                try: obj=json.loads(line)
                                except (ValueError,UnicodeDecodeError): continue
                                if isinstance(obj,dict) and obj.get('done') is True:
                                    for key in ('total_duration','load_duration','prompt_eval_count','prompt_eval_duration','eval_count','eval_duration'):
                                        if type(obj.get(key)) in (int,float) and obj[key]>=0: metrics[key]=obj[key]
                            yield block
                    finally:
                        state['http_timings'].append({'wall_seconds':round(time.monotonic()-started,6),
                            'status_code':response.status_code,'metrics_unavailable':not bool(metrics),
                            'stream_received':received,
                            **({'first_chunk_wall_seconds':first_chunk} if first_chunk is not None else {}), **metrics})
                        snapshot()
                response.aiter_raw=measured_raw
            else:
                capture_timing(response,started)
            return response

        def guarded_sync(client, request, *args, **kwargs):
            request=check_request(request, kwargs)
            started=time.monotonic()
            response = sync_send(client, request, *args, follow_redirects=False, **{k: v for k, v in kwargs.items() if k != "follow_redirects"})
            if json.loads(request.content).get("stream") is True:
                raise SafetyViolation("Synchronous streaming transport unsupported")
            capture_timing(response,started)
            if response.is_redirect:
                gate.blocked.append({"kind": "redirect", "reason": "Redirect response refused"})
                raise SafetyViolation("Redirect response refused")
            return response

        def capture_timing(response,started):
            timing={"wall_seconds":round(time.monotonic()-started,6),"status_code":response.status_code}
            try:
                data=response.json()
                for key in ("total_duration","load_duration","prompt_eval_count","prompt_eval_duration","eval_count","eval_duration"):
                    if key in data:
                        timing[key]=data[key]
            except Exception:
                timing["metrics_unavailable"]=True
            state["http_timings"].append(timing)
            snapshot()

        httpx.AsyncClient.send = guarded_async
        httpx.Client.send = guarded_sync

        def inspect_selected_artifact() -> dict:
            """Read only the bound synthetic artifact, with no input arguments."""
            result = selected_tool.invoke("inspect_selected_artifact", {})
            snapshot()
            return explanation_view(result, interactive=streaming, question=config['prompt'])

        def before_tool(tool, args, tool_context):
            try:
                result = selected_tool.invoke(tool.name, args)
                return explanation_view(result, interactive=streaming, question=config['prompt'])  # Full result stays in the audit log.
            finally:
                snapshot()

        model = LiteLlm(model="ollama_chat/" + MODEL, api_base=f"http://127.0.0.1:{PORT}",
                        timeout=30, num_retries=0, temperature=0, num_ctx=CONTEXT,
                        num_predict=MAX_TOKENS, keep_alive=keep_alive_seconds,
                        **({} if streaming else {"stream": False}))
        agent = Agent(name="edge_evidence_card2", model=model,
                      instruction=INTERACTIVE_INSTRUCTION if streaming else MODEL_INSTRUCTION,
                      tools=[inspect_selected_artifact], before_tool_callback=before_tool,
                      generate_content_config=types.GenerateContentConfig(
                          temperature=0, max_output_tokens=MAX_TOKENS))
        sessions = InMemorySessionService()
        await sessions.create_session(app_name="edge_evidence_card2", user_id="synthetic_reviewer", session_id="case")
        runner = Runner(agent=agent, app_name="edge_evidence_card2", session_service=sessions)
        pieces = []
        from google.adk.agents.run_config import StreamingMode
        async for event in runner.run_async(
            user_id="synthetic_reviewer", session_id="case",
            new_message=types.Content(role="user", parts=[types.Part(
                text=INSPECTION_REQUEST if streaming else config["prompt"])]),
            run_config=RunConfig(max_llm_calls=MAX_REQUESTS,
                                 streaming_mode=StreamingMode.SSE if streaming else StreamingMode.NONE)):
            if not getattr(event, "partial", False):
                if len(state["events"])<16: state["events"].append(sanitize_event(event))
            if streaming and getattr(event,"partial",False) and event.content:
                # Only model explanation partial text, and only after an accepted real inspection.
                # Ignore all intermediate function call/argument and first-call text fragments.
                parts=event.content.parts or []
                if not any(getattr(part,"function_call",None) or getattr(part,"thought",False) for part in parts):
                    chunk=''.join(part.text for part in parts if getattr(part,'text',None))
                    inspected=bool(selected_tool.calls and selected_tool.calls[-1].get('allowed') is True and
                                   len(gate.accepted)>=2 and gate.accepted[-1]['payload'].get('format'))
                    delta=projector.feed(chunk,inspected=inspected)
                    if delta and len(state['stream_chunks'])<256:
                        state['stream_chunks'].append({'seq':len(state['stream_chunks'])+1,
                            'phase':'explanation','delta':delta})
                        snapshot()
            usage = getattr(event, "usage_metadata", None)
            if usage is not None:
                state["usage"].append(usage.model_dump(mode="json", exclude_none=True))
            if not getattr(event,"partial",False) and event.is_final_response() and event.content:
                pieces += [part.text for part in (event.content.parts or []) if getattr(part, "text", None)]
            if not getattr(event,"partial",False): snapshot()
        state["answer"] = "\n".join(pieces) if pieces else None
        if not state["answer"] or not any(a["allowed"] for a in selected_tool.calls):
            raise RuntimeError("No complete tool-grounded answer")
        state["status"] = "RESPONSE_OBSERVED"
    except SafetyViolation:
        state["status"] = "SAFETY_REJECTED"
        state["error"] = {"type": "SafetyViolation", "message": "Model/worker boundary refused an operation"}
    except BaseException as exc:
        state["status"] = "HARNESS_ERROR"
        state["error"] = {"type": type(exc).__name__[:70], "message": "Worker exception (details retained only in private diagnostics)"}
    finally:
        state["finished_at_utc"] = utc()
        snapshot()
    return state


def main() -> int:
    # Called only with private supervisor-supplied arguments, not by the model.
    if len(sys.argv) != 3:
        return 1
    config_path, result_path = Path(sys.argv[1]), Path(sys.argv[2])
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        asyncio.run(run(config, result_path))
        return 0
    except BaseException:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
