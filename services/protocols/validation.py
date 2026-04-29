import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_DIR = PROJECT_ROOT / "protocols"

SCHEMA_FILES = {
    "research_task": "research_task.schema.json",
    "factor_score": "factor_score.schema.json",
    "debate_result": "debate_result.schema.json",
    "final_decision": "final_decision.schema.json",
    "data_quality": "data_quality.schema.json",
    "evidence_bundle": "evidence_bundle.schema.json",
}


@lru_cache(maxsize=None)
def _load_schema(schema_name: str) -> dict[str, Any]:
    try:
        schema_file = SCHEMA_FILES[schema_name]
    except KeyError as exc:
        raise ValueError(f"Unknown protocol schema: {schema_name}") from exc

    schema_path = PROTOCOL_DIR / schema_file
    return json.loads(schema_path.read_text(encoding="utf-8"))


def validate_protocol(schema_name: str, payload: dict[str, Any]) -> None:
    schema = _load_schema(schema_name)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))

    if not errors:
        return

    first_error = errors[0]
    path = ".".join(str(part) for part in first_error.path) or "<root>"
    raise ValueError(
        f"{schema_name} protocol validation failed at {path}: {first_error.message}"
    )
