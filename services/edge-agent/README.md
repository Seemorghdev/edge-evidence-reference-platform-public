# Edge Agent

The Edge Agent is a bounded inspection service. Its default path is deterministic and read-only; an optional model adapter is default-off and does not confer mutation authority.

## HTTP surface

- `GET /health`
- `GET /healthz`
- `POST /api/v1/inspect`

Both health routes report `mutation_authorized: false`.

The Agent receives a projection and returns a classification/explanation. It does not execute workers, mutate evidence, deploy infrastructure, or gain operational authority from optional model integration.

Run locally with `make agent` or the root Compose workflow.
