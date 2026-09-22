# Reviewer walkthrough

This path is intentionally local and credential-free.

## 1. Install and validate

Requirements: Python 3.11–3.13 and Docker with Compose support.

```bash
python scripts/install_workspace.py --dev
make check
```

The checks lint/test the application, validate the projection boundary, and parse the Compose model. They do not contact or mutate a cloud provider.

## 2. Run the three services

```bash
docker compose -f deploy/compose/docker-compose.yml \
  up --build evidence-api edge-agent web-ui
```

Open <http://localhost:8082/>. Expect exactly three synthetic artifacts: `complete`, `deferred`, and `prepared`.

Useful endpoints:

```bash
curl -fsS http://localhost:8080/healthz
curl -fsS http://localhost:8080/api/v1/artifacts
curl -fsS http://localhost:8081/healthz
```

The Edge Agent health response must include `mutation_authorized: false`.

## 3. Run the integration check

```bash
docker compose -f deploy/compose/docker-compose.yml \
  --profile tools run --rm integration-runner
```

This reads the three projections and requests inspection for each over HTTP. It performs no worker or provider action.

## 4. Optional bounded load

```bash
docker compose -f deploy/compose/docker-compose.yml \
  --profile load run --rm load-generator
```

The load tool targets only the local Evidence API and caps requests.

## 5. Inspect generic deployment intent

`deploy/kubernetes/base/` contains generic workload manifests for the same three services. They are review material only: no live cluster, provider, registry, account, or identity is bound here.

## 6. Clean shutdown

```bash
docker compose -f deploy/compose/docker-compose.yml down --remove-orphans
```

For the trust model, continue with [the authority boundary](authority-boundary.md).
