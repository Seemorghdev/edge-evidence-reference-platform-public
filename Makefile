.PHONY: install test lint check projection-check api agent ui integration compose-config

install:
	python scripts/install_workspace.py --dev

test:
	pytest

lint:
	ruff check packages services tools tests scripts

projection-check:
	python scripts/check_projection.py

compose-config:
	docker compose -f deploy/compose/docker-compose.yml config --quiet

check: lint test projection-check compose-config

api:
	uvicorn edge_evidence_evidence_api.app:app --host 0.0.0.0 --port 8080

agent:
	uvicorn edge_evidence_edge_agent.app:app --host 0.0.0.0 --port 8081

ui:
	uvicorn edge_evidence_web_ui.app:app --host 0.0.0.0 --port 8082

integration:
	integration-runner run
