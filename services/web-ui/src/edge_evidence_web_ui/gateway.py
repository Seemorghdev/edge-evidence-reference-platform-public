"""Single-origin, single-process assembly for a bounded synthetic demo.

This is a deployment adapter, not a replacement for the independently packaged
services. It exposes read-only API/Agent routes and deliberately omits the
Evidence API's demo-reset endpoint.
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from edge_evidence_edge_agent.app import app as agent_service
from edge_evidence_evidence_api.app import app as evidence_service
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .app import SERVICE_ROOT

templates = Jinja2Templates(directory=str(SERVICE_ROOT / "templates"))
app = FastAPI(
    title="Edge Evidence Synthetic Demo",
    version="0.2.0",
    description="Same-origin assembly of the read-only synthetic API, Agent, and Web UI.",
)


@app.get("/healthz", tags=["platform"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"evidence_api_url": "", "edge_agent_url": ""},
    )


def _routes_from(source: FastAPI, *, allowed: set[str]) -> APIRouter:
    router = APIRouter()
    for route in source.router.routes:
        if isinstance(route, APIRoute) and route.path in allowed:
            router.routes.append(route)
    return router


app.include_router(
    _routes_from(
        evidence_service,
        allowed={
            "/readyz",
            "/api/v1/artifacts",
            "/api/v1/artifacts/{artifact_id}",
            "/api/v1/receipts",
            "/api/v1/receipts/{receipt_id}",
        },
    )
)
app.include_router(
    _routes_from(
        agent_service,
        allowed={"/health", "/api/v1/inspect"},
    )
)
app.mount(
    "/static",
    StaticFiles(directory=str(Path(SERVICE_ROOT) / "static")),
    name="static",
)


def main() -> None:
    uvicorn.run(
        "edge_evidence_web_ui.gateway:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8080")),
    )


if __name__ == "__main__":
    main()
