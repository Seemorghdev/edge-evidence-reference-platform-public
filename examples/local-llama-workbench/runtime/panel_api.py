"""Same-origin loopback API; no user-provided transport/source authority."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import json

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from boundaries import MODEL
from proof_snapshot import ProofUnavailable, load_snapshot
from panel_supervisor import FIXTURE_FILES, PanelSupervisor, ROOT


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    fixture_id: str
    question: str = Field(min_length=1, max_length=2000)


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def create_app(supervisor: PanelSupervisor | None = None, *, port: int = 0) -> FastAPI:
    # Application construction is inert: no network, process or model startup.
    svc = supervisor if supervisor is not None else PanelSupervisor()
    allowed_host = f"127.0.0.1:{port}"

    @asynccontextmanager
    async def lifespan(app):
        # Only app startup can initiate the single bounded warm preload.
        # Never import-time; no automatic model installation or fallback.
        if not getattr(svc.transport,'mock',False):svc.start_prepare_once()
        yield
        if not await asyncio.to_thread(svc.close):
            # Cleanup failure is not silently treated as a successful shutdown.
            raise RuntimeError("Owned local worker/server cleanup could not be verified")

    app = FastAPI(title="Edge Evidence local experiment", docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.supervisor = svc

    @app.middleware("http")
    async def same_origin(request: Request, call_next):
        host = request.headers.get("host", "")
        origin = request.headers.get("origin")
        fetch_site = request.headers.get("sec-fetch-site")
        if host != allowed_host or (origin is not None and origin != f"http://{allowed_host}") or (
            fetch_site is not None and fetch_site not in ("same-origin", "none")) or (
            request.method in ("POST", "PUT", "PATCH", "DELETE") and origin != f"http://{allowed_host}"):
            return JSONResponse({"error": "Origin/Host rejected"}, status_code=403)
        result = await call_next(request)
        result.headers.update({
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        })
        return result

    @app.get("/")
    async def index():
        return FileResponse(ROOT / "ui" / "index.html", media_type="text/html")

    @app.get("/styles.css")
    async def styles():
        return FileResponse(ROOT / "ui" / "styles.css", media_type="text/css")

    @app.get("/app.js")
    async def script():
        return FileResponse(ROOT / "ui" / "app.js", media_type="text/javascript")

    @app.get("/proof.js")
    async def proof_script():
        return FileResponse(ROOT / "ui" / "proof.js", media_type="text/javascript")

    @app.get("/api/proof")
    async def proof():
        try:
            return await asyncio.to_thread(load_snapshot)
        except ProofUnavailable:
            return JSONResponse({"state":"unavailable","error":"Retained proof unavailable or integrity check failed"},status_code=503)

    @app.get("/api/config")
    async def config():
        return {"name": "Edge Evidence — local Ollama inspector experiment",
                "model": MODEL, "synthetic": True, "mock_transport": bool(getattr(svc.transport, "mock", False)),
                "fixtures": [{"id": key, "label": label} for key, (label, _) in FIXTURE_FILES.items()]}

    @app.get('/api/model/readiness')
    async def readiness():
        return svc.readiness()

    @app.post('/api/model/prepare')
    async def prepare(payload: EmptyRequest):
        state=svc.readiness()['state']
        if state in ('busy','warming','cleanup_blocked'):
            return JSONResponse({'state':state,'error':'Preparation blocked by active work or cleanup'},status_code=409)
        import threading
        threading.Thread(target=svc.prepare,daemon=True,name='edge-evidence-prepare').start()
        return JSONResponse({'state':'warming','note':'Preparation is not a question or a model answer'},status_code=202)

    @app.get("/api/facts/{fixture_id}")
    async def facts(fixture_id: str):
        if fixture_id not in FIXTURE_FILES:
            return JSONResponse({"error": "Unknown synthetic fixture"}, status_code=404)
        try:
            return await asyncio.to_thread(svc.facts, fixture_id)
        except Exception:
            return JSONResponse({"error": "Pinned inspector or source unavailable", "state": "harness_error"}, status_code=503)

    @app.post("/api/ask")
    async def ask(payload: AskRequest):
        if payload.fixture_id not in FIXTURE_FILES or not payload.question.strip() or "\x00" in payload.question:
            return JSONResponse({"error": "Invalid fixture or question", "state": "invalid_input"}, status_code=422)
        try:
            return await asyncio.to_thread(svc.ask, payload.fixture_id, payload.question)
        except RuntimeError:
            return JSONResponse({"error": "Inference busy or cleanup unverified", "state": "request_blocked"}, status_code=409)
        except Exception:
            return JSONResponse({"error": "Local supervisor error", "state": "harness_error"}, status_code=500)

    @app.post("/api/turns")
    async def start_turn(payload: AskRequest):
        if payload.fixture_id not in FIXTURE_FILES or not payload.question.strip() or "\x00" in payload.question:
            return JSONResponse({"error": "Invalid fixture or question", "state": "invalid_input"}, status_code=422)
        try:
            turn_id = svc.start(payload.fixture_id, payload.question)
            return JSONResponse({"turn_id": turn_id, "state": "pending"}, status_code=202)
        except RuntimeError:
            return JSONResponse({"error": "Inference busy or cleanup unverified", "state": "request_blocked"}, status_code=409)
        except Exception:
            return JSONResponse({"error": "Local supervisor error", "state": "harness_error"}, status_code=500)

    @app.get("/api/turns/{turn_id}")
    async def read_turn(turn_id: str):
        # Opaque IDs are server-generated and strictly scoped; no trace path input.
        if len(turn_id) != 32 or any(c not in "0123456789abcdef" for c in turn_id):
            return JSONResponse({"error": "Unknown turn"}, status_code=404)
        row = svc.get_turn(turn_id)
        if row is None:
            return JSONResponse({"error": "Unknown or evicted turn"}, status_code=404)
        return row

    @app.get('/api/turns/{turn_id}/events')
    async def stream_turn(turn_id: str, request: Request):
        # Subscribe/reconnect only: a GET cannot reserve or restart inference.
        if len(turn_id)!=32 or any(c not in '0123456789abcdef' for c in turn_id) or svc.get_turn(turn_id) is None:
            return JSONResponse({'error':'Unknown or evicted turn'},status_code=404)
        async def events():
            previous=-1
            while True:
                row=svc.get_turn(turn_id)
                if row is None:break
                revision=row['revision']
                if revision!=previous:
                    previous=revision
                    # Cumulative bounded draft makes reconnect idempotent, no duplicate concatenation.
                    payload=json.dumps(row,ensure_ascii=True,separators=(',',':'))
                    yield f'id: {turn_id}:{revision}\nevent: turn\ndata: {payload}\n\n'
                if row['status']=='finished':break
                if await request.is_disconnected():break
                await asyncio.sleep(.1)
        return StreamingResponse(events(),media_type='text/event-stream',headers={
            'Cache-Control':'no-store','X-Accel-Buffering':'no'})

    @app.post("/api/turns/{turn_id}/cancel")
    async def cancel_turn(turn_id: str, payload: EmptyRequest):
        if len(turn_id) != 32 or any(c not in "0123456789abcdef" for c in turn_id):
            return JSONResponse({"error": "Unknown turn"}, status_code=404)
        # A stale cancellation is a no-op, never applied to a newer turn.
        if svc.get_turn(turn_id) is None:
            return JSONResponse({"error": "Unknown or evicted turn"}, status_code=404)
        return {"cancellation_requested": svc.cancel(turn_id),
                "note": "A new turn remains blocked until owned-process cleanup completes."}

    @app.post("/api/turns/clear")
    async def clear_turns(payload: EmptyRequest):
        if not svc.clear_history():
            return JSONResponse({"error": "Active work or cleanup unverified", "state": "request_blocked"}, status_code=409)
        return {"cleared": True}

    @app.post("/api/cancel")
    async def cancel(payload: EmptyRequest):
        return {"cancellation_requested": svc.cancel(),
                "note": "A new turn remains blocked until owned-process cleanup completes."}

    return app
