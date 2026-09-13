import pytest
from pydantic import ValidationError

from users_api.api.schemas.preferences import UpdatePreferencesRequest


def field_errors(error: ValidationError) -> list[str]:
    return [str(problem["loc"][0]) for problem in error.errors()]


def test_e1_h7_ca3_rejects_malformed_payloads():
    # An unknown field, not silently ignored.
    with pytest.raises(ValidationError) as error:
        UpdatePreferencesRequest(theme="dark")
    assert field_errors(error.value) == ["theme"]

    # The wrong type for a field that is otherwise a valid enum member.
    with pytest.raises(ValidationError) as error:
        UpdatePreferencesRequest(profile_visibility=123)
    assert field_errors(error.value) == ["profile_visibility"]

    # Explicit null: neither preference has an "unset" state to fall back to.
    with pytest.raises(ValidationError) as error:
        UpdatePreferencesRequest(feed_language=None)
    assert field_errors(error.value) == ["feed_language"]


def test_e1_h7_ca4_rejects_values_outside_the_enum():
    with pytest.raises(ValidationError) as error:
        UpdatePreferencesRequest(profile_visibility="private")
    assert field_errors(error.value) == ["profile_visibility"]

    with pytest.raises(ValidationError) as error:
        UpdatePreferencesRequest(feed_language="fr")
    assert field_errors(error.value) == ["feed_language"]


def test_omitting_a_field_leaves_it_unset():
    payload = UpdatePreferencesRequest(profile_visibility="protected")
    assert payload.model_dump(exclude_unset=True) == {"profile_visibility": "protected"}
