FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8082
WORKDIR /app
RUN groupadd --gid 65532 app && useradd --uid 65532 --gid app --create-home app
COPY services/web-ui /build/project
RUN python -m pip install --no-cache-dir /build/project && rm -rf /build
USER 65532:65532
EXPOSE 8082
CMD ["uvicorn", "edge_evidence_web_ui.app:app", "--host", "0.0.0.0", "--port", "8082"]
