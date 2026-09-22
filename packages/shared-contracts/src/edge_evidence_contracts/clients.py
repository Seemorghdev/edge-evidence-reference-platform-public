"""Small typed clients for the public service contracts."""

from __future__ import annotations

from types import TracebackType
from typing import Self

import httpx

from .models import AgentInspection, ArtifactProjection


class EvidenceApiClient:
    def __init__(self, base_url: str, *, timeout: float = 5.0) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def health(self) -> dict[str, str]:
        response = self._client.get("/healthz")
        response.raise_for_status()
        return response.json()

    def list_artifacts(self) -> list[ArtifactProjection]:
        response = self._client.get("/api/v1/artifacts")
        response.raise_for_status()
        return [ArtifactProjection.model_validate(item) for item in response.json()]


class EdgeAgentClient:
    def __init__(self, base_url: str, *, timeout: float = 5.0) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def health(self) -> dict[str, str | bool]:
        response = self._client.get("/healthz")
        response.raise_for_status()
        return response.json()

    def inspect(self, artifact: ArtifactProjection) -> AgentInspection:
        response = self._client.post(
            "/api/v1/inspect",
            json=artifact.model_dump(mode="json"),
        )
        response.raise_for_status()
        return AgentInspection.model_validate(response.json())
