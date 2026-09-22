# Evidence API

The Evidence API is a read-oriented synthetic projection service. It exposes deterministic artifact/receipt views for demonstrations and integration tests; it is not a worker database and does not execute workers.

## HTTP surface

- `GET /healthz`
- `GET /readyz` with `authority: synthetic-only`
- `GET /api/v1/artifacts`
- `GET /api/v1/artifacts/{artifact_id}`
- `GET /api/v1/receipts`
- `GET /api/v1/receipts/{receipt_id}`
- `POST /api/v1/demo/reset`

The in-process store is disposable. A successful API response is a projection/demo signal, not evidence-authority mutation.

Run locally with `make api` or the root Compose workflow.
