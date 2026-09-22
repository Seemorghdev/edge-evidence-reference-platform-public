# Web UI

The Web UI is the presentation service for the synthetic artifact journey. It owns its template/static assets and does not import application code from the Evidence API or Edge Agent.

## Browser flow

Local Compose uses explicit loopback URLs for the Evidence API and Edge Agent. A same-origin deployment can leave both backend URL values empty so browser fetches use relative paths such as `/api/v1/artifacts` and `/api/v1/inspect`.

## HTTP surface

- `GET /healthz`
- `GET /`
- `/static/*`

The UI is presentation only and cannot become evidence or infrastructure mutation authority.

Run locally with `make ui` or the root Compose workflow.
