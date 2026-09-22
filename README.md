# Edge Evidence Reference Platform

A history-free, recruiter-facing application projection for evidence-first systems engineering.

The product demonstrates a strict authority split: deterministic workers own evidence and state outside this runtime; the **Evidence API** exposes disposable synthetic projections; the **Edge Agent** performs bounded read-only inspection; and the **Web UI** presents the journey without gaining mutation authority.

## Three-service product story

| Service | Responsibility | Authority boundary |
| --- | --- | --- |
| Evidence API | Serves deterministic synthetic artifact and receipt projections. | Disposable projection only; not evidence authority. |
| Edge Agent | Classifies supplied projections and explains state. | Read-only inspection; cannot execute workers or mutate evidence/infrastructure. |
| Web UI | Renders artifacts and requests inspection from the browser. | Presentation only. |

The optional model/ADK adapter is disabled by default. Enabling it does not change the inspection-only authority contract.

## Quick reviewer path

Requirements: Python 3.11–3.13 and Docker with Compose support. No cloud account or provider credential is required.

```bash
python scripts/install_workspace.py --dev
make check

docker compose -f deploy/compose/docker-compose.yml \
  up --build evidence-api edge-agent web-ui
```

Open <http://localhost:8082/>. The page should render exactly three deterministic synthetic artifacts with states `complete`, `deferred`, and `prepared`. Inspecting the complete artifact returns the deterministic `healthy-complete` classification.

Run the bounded cross-service check:

```bash
docker compose -f deploy/compose/docker-compose.yml \
  --profile tools run --rm integration-runner
```

Optional bounded local load:

```bash
docker compose -f deploy/compose/docker-compose.yml \
  --profile load run --rm load-generator
```

Clean shutdown:

```bash
docker compose -f deploy/compose/docker-compose.yml down --remove-orphans
```

## Browser and same-origin integration

Local Compose uses explicit loopback API/Agent origins and an explicit CORS allowlist. For a same-origin deployment, leave the Web UI backend URL values empty so browser requests remain relative to the page origin and route through the deployment's application gateway.

The generic workload intent under `deploy/kubernetes/base/` contains no live provider, account, cluster, registry, identity, endpoint, or state coordinates and grants no deployment authority.

## Reviewer navigation

- [Hands-on walkthrough](docs/reviewer-walkthrough.md)
- [Architecture](docs/architecture/overview.md)
- [Authority boundary](docs/authority-boundary.md)
- [Evidence API](services/evidence-api/README.md)
- [Edge Agent](services/edge-agent/README.md)
- [Web UI](services/web-ui/README.md)
- [Shared contracts](packages/shared-contracts/)
- [Generic Kubernetes workload intent](deploy/kubernetes/base/)
- [Read-only CI](.github/workflows/required.yml)

## What is and is not claimed

Proven by this projection's code/tests:

- three independently packaged services;
- deterministic three-artifact synthetic behavior;
- read-only inspection with `mutation_authorized=false`;
- browser presentation with explicit local CORS and a generic same-origin mode;
- credential-free local container workflow;
- generic non-provider-specific workload manifests.

Not claimed:

- production traffic, durability, production SLOs, multi-region availability, or autonomous operations;
- ownership of worker evidence/state;
- provider deployment, cloud infrastructure, credentials, live endpoints, or operational authority.

## Repository map

```text
services/                 three runtime services
packages/shared-contracts stable models and HTTP clients
contracts/                public artifact/receipt JSON schemas
fixtures/                 deterministic synthetic examples
tools/                    bounded integration and load tools
deploy/compose/           local reviewer runtime
deploy/kubernetes/base/   generic workload intent only
docs/                     recruiter-facing architecture and authority docs
tests/                    application and projection-boundary tests
```
