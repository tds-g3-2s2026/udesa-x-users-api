"""Candidates carry the opaque position needed after visibility filtering."""

from dataclasses import dataclass

from users_api.app.models.user import User

SEARCH_BATCH_SIZE = 50


@dataclass(frozen=True)
class SearchCandidate:
    user: User
    cursor: str
