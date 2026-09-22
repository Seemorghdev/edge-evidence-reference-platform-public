"""Small functional web UI for the synthetic artifact journey."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

SERVICE_ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(SERVICE_ROOT / "templates"))
app = FastAPI(title="Edge Evidence Web UI", version="0.2.0")
app.mount("/static", StaticFiles(directory=str(SERVICE_ROOT / "static")), name="static")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "evidence_api_url": os.getenv("EVIDENCE_API_URL", "http://localhost:8080"),
            "edge_agent_url": os.getenv("EDGE_AGENT_URL", "http://localhost:8081"),
        },
    )


def main() -> None:
    uvicorn.run(
        "edge_evidence_web_ui.app:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8082")),
    )


if __name__ == "__main__":
    main()
