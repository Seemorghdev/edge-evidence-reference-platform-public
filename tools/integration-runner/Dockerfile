FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /workspace
RUN groupadd --gid 65532 app && useradd --uid 65532 --gid app --create-home app
COPY packages/shared-contracts /build/shared-contracts
COPY tools/integration-runner /build/project
RUN python -m pip install --no-cache-dir /build/shared-contracts /build/project && rm -rf /build
USER 65532:65532
ENTRYPOINT ["integration-runner"]
