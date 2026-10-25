"""The published event schemas, loaded for the tests that check a message against them."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts" / "events"


def validator_for(event_type: str) -> Draft202012Validator:
    """Formats switched on: otherwise `uuid`, `email`, `uri` and `date-time` are plain strings."""
    schema = json.loads((CONTRACTS / f"{event_type}.json").read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
