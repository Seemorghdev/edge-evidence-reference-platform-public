# Model-free hosted Gateway

The Gateway serves Inspect, a digest-checked retained synthetic Proof, and an Ask
explanation linking to the optional local workbench. It imports the native public
Evidence API and deterministic inspector. Missing imports fail startup; there is no
fixture-service fallback, hosted Ollama, inference credential, or worker execution.

The stable entry point remains `edge_evidence_web_ui.gateway:app`.
The generic three-service application is unchanged.

## Reproduce the container

Obtain a separate checkout of the public Reference Platform revision specified in
`hosted_packaging/PUBLIC-SOURCE-BLOBS.json`. Then, from the repository root:

```sh
python services/web-ui/hosted_packaging/stage_build_context.py \
  --public-checkout /path/to/pinned-public-checkout --output /path/to/new-context
docker build --platform linux/amd64 -f /path/to/new-context/Dockerfile.gateway \
  -t edge-evidence-gateway:review /path/to/new-context
docker run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  -e PORT=18083 -p 127.0.0.1:18083:18083 edge-evidence-gateway:review
```

The context contains only enumerated Gateway files, ten pinned native public source
blobs, and three preserved upstream notices. Do not build this Dockerfile against an
unrestricted repository root. No Git history, local model, research, or credentials
enter the context. The runtime installs 17 hash-locked packages and runs as UID 65532.
Only Linux/amd64 is locked; ARM uses emulation, not a native-performance baseline.

The supplied proof remains a cached synthetic filesystem demonstration. A matching
capture digest establishes retained-byte integrity, not a fresh execution or physical
NAS/cloud acceptance. Corrupt proof returns unavailable, never inferred success.

Proof playback steps through that same snapshot: Processor, handoff, Replication,
readback and replay. Each step quotes recorded fields by JSON path and keeps the page's
own wording labelled as presentation. The standalone Processor and Replication proofs
appear only as recorded passes because their step-level summaries are not in the
snapshot. A missing recorded field or a source/target mismatch returns unavailable.
Playback adds no route and runs no worker, target read or model.

These packaging instructions do not authorize image publication or deployment.
