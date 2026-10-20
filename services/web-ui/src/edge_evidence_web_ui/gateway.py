"""Stable same-origin Gateway entry point; no model or worker execution."""

import os

import uvicorn

from .workbench.gateway import app

__all__ = ["app", "main"]


def main() -> None:
    if os.getenv("EDGE_AGENT_ENABLE_ADK", "0") != "0":
        raise SystemExit("ADK cannot be enabled in the hosted Gateway")
    if os.getenv("EDGE_REVIEW_TEST_FIXTURES", "0") != "0":
        raise SystemExit("Fixture services cannot be enabled in the hosted Gateway")
    port = os.getenv("PORT", "8080")
    if not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise SystemExit("PORT must be in range 1..65535")
    uvicorn.run("edge_evidence_web_ui.gateway:app", host="0.0.0.0", port=int(port))


if __name__ == "__main__":
    main()
