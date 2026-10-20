"""Stable component contracts without worker-internal imports."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, model_validator


class SourceContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: str
    commit: str | None
    license: str


class BuildContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: str
    dockerfile: str


class ContainerContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image: str
    image_digest: str | None
    entrypoint: str
    build: BuildContract | None


class PackageContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distribution: str
    public_module: str
    exports: list[str] = Field(default_factory=list)


class CommandContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executable: str
    args: list[str]


class CliContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executable: str
    args: list[str]
    package_entry_points: dict[str, str] = Field(default_factory=dict)
    read_only: CommandContract | None = None


class ComponentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_version: str
    kind: str
    name: str
    version: str
    provisional: bool
    source: SourceContract
    container: ContainerContract
    package: PackageContract
    cli: CliContract
    schemas: dict[str, str]
    outputs: list[str]
    authority: list[str]
    prohibited: list[str]


class ProcessorRunSummary(BaseModel):
    """Public JSON emitted by ``processor-worker run``."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["pass", "deferred"]
    snapshot_eligible: NonNegativeInt
    already_complete: NonNegativeInt
    prepared_resumed: NonNegativeInt
    newly_completed: NonNegativeInt
    deferred: NonNegativeInt
    remaining: NonNegativeInt

    @model_validator(mode="after")
    def validate_accounting(self) -> ProcessorRunSummary:
        completed = self.already_complete + self.prepared_resumed + self.newly_completed
        if completed + self.remaining != self.snapshot_eligible:
            raise ValueError("processor summary counts do not reconcile")
        if self.deferred not in {0, 1}:
            raise ValueError("processor deferred count must be zero or one")
        if self.status == "pass" and self.remaining != 0:
            raise ValueError("pass status requires zero remaining work")
        if self.status == "deferred" and self.remaining == 0:
            raise ValueError("deferred status requires remaining work")
        return self


def load_component(path: Path) -> ComponentManifest:
    return ComponentManifest.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_components(directory: Path) -> dict[str, ComponentManifest]:
    manifests: dict[str, ComponentManifest] = {}
    for path in sorted(directory.glob("*.yaml")):
        manifest = load_component(path)
        manifests[manifest.name] = manifest
    return manifests


def _render(executable: str, args: list[str], values: dict[str, str]) -> list[str]:
    return [executable, *(arg.format_map(values) for arg in args)]


def render_command(manifest: ComponentManifest, values: dict[str, str]) -> list[str]:
    return _render(manifest.cli.executable, manifest.cli.args, values)


def render_container_command(
    manifest: ComponentManifest,
    values: dict[str, str],
) -> list[str]:
    return _render(manifest.container.entrypoint, manifest.cli.args, values)


def render_read_only_command(
    manifest: ComponentManifest,
    values: dict[str, str],
) -> list[str] | None:
    if manifest.cli.read_only is None:
        return None
    return _render(
        manifest.cli.read_only.executable,
        manifest.cli.read_only.args,
        values,
    )


def load_processor_summary(path: Path) -> ProcessorRunSummary:
    return ProcessorRunSummary.model_validate_json(path.read_text(encoding="utf-8"))
