import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from users_api.app.audit_events import AuditEvent


def example():
    schema = json.loads(Path("contracts/events/admin.action_recorded.v1.json").read_text())
    value = schema["examples"][0]
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    return value


def test_e5_h6_event_contract_matches_consumer():
    event = AuditEvent.model_validate(example())
    assert str(event.entry().id) == example()["id"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor_email", "invalid"),
        ("actor_id", "invalid"),
        ("action", "admin.created"),
        ("target_type", "post"),
        ("details", {"reports_count": 0}),
        ("details", {"reports_count": True}),
    ],
)
def test_e5_h6_invalid_audit_data_is_rejected(field, value):
    body = example()
    body["data"][field] = value
    with pytest.raises(ValidationError):
        AuditEvent.model_validate(body)


def test_e5_h6_date_requires_timezone_and_source_is_checked():
    body = example()
    body["time"] = "2026-10-25T10:00:00"
    with pytest.raises(ValidationError):
        AuditEvent.model_validate(body)
    body = example()
    body["source"] = "unknown"
    with pytest.raises(ValidationError):
        AuditEvent.model_validate(body)
