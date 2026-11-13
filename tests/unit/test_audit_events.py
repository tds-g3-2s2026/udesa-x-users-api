import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from users_api.app.audit_events import AuditEvent


def example(index: int = 0):
    """The contract's examples: 0 closes reports, 1 cleans a post."""
    schema = json.loads(Path("contracts/events/admin.action_recorded.v1.json").read_text())
    value = schema["examples"][index]
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


def test_e5_h10_a_cleaned_post_is_recorded_with_its_author():
    entry = AuditEvent.model_validate(example(1)).entry()

    assert (entry.action, entry.target_type) == ("post.content_cleaned", "post")
    assert str(entry.target_id) == example(1)["data"]["target_id"]
    # Stored as JSON: the id travels back as text, the same as it came.
    assert entry.details == {"author_id": example(1)["data"]["details"]["author_id"]}


@pytest.mark.parametrize(
    "field,value",
    [
        ("target_type", "user"),
        ("details", {}),
        ("details", {"author_id": "invalid"}),
        ("details", {"reports_count": 1}),
    ],
)
def test_e5_h10_a_cleaned_post_with_the_wrong_target_or_details_is_rejected(field, value):
    body = example(1)
    body["data"][field] = value
    with pytest.raises(ValidationError):
        AuditEvent.model_validate(body)
