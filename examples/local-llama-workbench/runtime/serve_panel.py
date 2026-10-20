"""Launch a loopback-only local panel on a freely selected UI port."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description="Edge Evidence local-only Ollama panel")
    parser.add_argument("--mock-transport", action="store_true", help="EXPLICIT TEST ONLY: no Ollama calls")
    parser.add_argument("--mock-outcome", default="completed",
                        choices=("completed", "withheld", "blocked", "timeout", "unavailable", "invalid", "error"))
    args = parser.parse_args(argv)
    from panel_supervisor import PanelSupervisor, RealTransport, MockTransport, ROOT
    from panel_api import create_app
    import uvicorn

    # Keep the UI ephemeral; no probing and killing another local listener.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        port = sock.getsockname()[1]
        transport = (MockTransport(args.mock_outcome) if args.mock_transport else
                     RealTransport(Path(os.getenv("EDGE_EVIDENCE_PUBLIC_SOURCE", ROOT / "public-source")),
                       Path(os.environ["EDGE_EVIDENCE_OLLAMA_BIN"]) if os.environ.get("EDGE_EVIDENCE_OLLAMA_BIN") else None,
                       Path(os.environ["EDGE_EVIDENCE_MODEL_STORE"]) if os.environ.get("EDGE_EVIDENCE_MODEL_STORE") else None))
        svc = PanelSupervisor(transport=transport)
        print(f"Local experiment: http://127.0.0.1:{port}/", flush=True)
        if args.mock_transport:
            print("TEST MODE — EXPLICIT MOCKED TRANSPORT; NOT AN OLLAMA RESULT", flush=True)
        app = create_app(svc, port=port)
        # Uvicorn accepts a pre-bound IPv4 socket, eliminating free-port TOCTOU.
        config = uvicorn.Config(app, log_level="warning", access_log=False)
        server = uvicorn.Server(config)
        try:
            server.run(sockets=[sock])
        finally:
            if not svc.close():
                print("ERROR: owned-process cleanup unverified", file=sys.stderr)
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
