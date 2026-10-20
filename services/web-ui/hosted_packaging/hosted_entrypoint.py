"""No test fixtures, model/service discovery, shell interpolation or mutable startup."""

import os

import uvicorn


def main():
    if os.environ.get("EDGE_REVIEW_TEST_FIXTURES", "0") != "0":
        raise SystemExit("Fixture service mode is forbidden in the hosted image")
    if os.environ.get("EDGE_AGENT_ENABLE_ADK", "0") != "0":
        raise SystemExit("ADK cannot be enabled in the hosted image")
    port = os.environ.get("PORT", "8080")
    if not port.isdecimal() or not (1 <= int(port) <= 65535):
        raise SystemExit("PORT must be an integer in range 1..65535")
    uvicorn.run(
        "edge_evidence_web_ui.gateway:app", host="0.0.0.0", port=int(port), log_level="info"
    )


if __name__ == "__main__":
    main()
