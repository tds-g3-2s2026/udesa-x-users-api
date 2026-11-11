"""Privacy and personalisation settings a user can change about themselves."""

from pydantic import BaseModel, ConfigDict, field_validator

from users_api.app.models.user import MIN_INTERESTS, FeedLanguage, Interest, ProfileVisibility


class PreferencesResponse(BaseModel):
    profile_visibility: ProfileVisibility
    feed_language: FeedLanguage
    interests: list[Interest]


def reject_null_when_present(value: object) -> object:
    """Refuse an explicit `null`, the same way `UpdateProfileRequest` does.

    Pydantic only calls a field validator when the key is present in the
    payload at all — omitting a preference entirely skips validation and
    leaves it unchanged, which is what makes this a partial update. Neither
    preference has an "unset" state to fall back to, so a `null` sent on
    purpose is as malformed as a value outside the enum.
    """
    if value is None:
        raise ValueError("No puede ser nulo")
    return value


class UpdatePreferencesRequest(BaseModel):
    """A partial update: only the fields present in the payload change.

    Both fields are the enum itself and not a plain string, so a value outside
    the two or three defined ones is rejected before any business logic runs,
    with no separate check needed. `extra="forbid"` is what rejects an unknown
    preference with a 422 instead of silently ignoring it.
    """

    model_config = ConfigDict(extra="forbid")

    profile_visibility: ProfileVisibility | None = None
    feed_language: FeedLanguage | None = None
    # Plain strings and not the enum: an unknown code is then reported on
    # `interests` itself and not on its position in the list.
    interests: list[str] | None = None

    _reject_null_visibility = field_validator("profile_visibility")(reject_null_when_present)
    _reject_null_language = field_validator("feed_language")(reject_null_when_present)

    @field_validator("interests")
    @classmethod
    def interests_must_be_a_valid_choice(cls, value: list[str] | None) -> list[Interest]:
        """The whole list is replaced, so it is checked whole."""
        if value is None:
            raise ValueError("No puede ser nulo")
        known = {interest.value for interest in Interest}
        if any(code not in known for code in value):
            raise ValueError(f"Los intereses válidos son: {', '.join(sorted(known))}")
        if len(set(value)) != len(value):
            raise ValueError("No se puede repetir un interés")
        if len(value) < MIN_INTERESTS:
            raise ValueError(f"Elegí al menos {MIN_INTERESTS} intereses")
        return [Interest(code) for code in value]
