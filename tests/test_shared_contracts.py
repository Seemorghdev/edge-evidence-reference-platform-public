import json
from pathlib import Path

from edge_evidence_contracts.models import ArtifactProjection
from jsonschema import validate

ROOT = Path(__file__).resolve().parents[1]


def test_artifact_fixtures_match_model_and_schema() -> None:
    schema = json.loads((ROOT / "contracts/artifact.schema.json").read_text(encoding="utf-8"))
    fixtures = sorted((ROOT / "fixtures").glob("artifact-*.json"))
    assert [path.name for path in fixtures] == [
        "artifact-complete.json",
        "artifact-deferred.json",
        "artifact-prepared.json",
    ]
    states = set()
    for path in fixtures:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate(payload, schema)
        projection = ArtifactProjection.model_validate(payload)
        states.add(projection.state.value)
    assert states == {"complete", "deferred", "prepared"}
