FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
RUN groupadd --gid 65532 app && useradd --uid 65532 --gid app --create-home app
COPY packages/shared-contracts /build/shared-contracts
COPY services/evidence-api /build/project
RUN python -m pip install --no-cache-dir /build/shared-contracts /build/project && rm -rf /build
USER 65532:65532
EXPOSE 8080
CMD ["uvicorn", "edge_evidence_evidence_api.app:app", "--host", "0.0.0.0", "--port", "8080"]
