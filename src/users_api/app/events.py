"""The events this service publishes, as CloudEvents 1.0 envelopes.

Pure functions: they take what happened and return the envelope, nothing here
touches a database or a broker. The shape of each `data` is fixed by the JSON
Schemas under `contracts/events/` (ADR-017), and the tests validate every
envelope built here against them.

Several carry a secret (`verification_url`, `token`). Whoever handles an `Event`
must not log its envelope.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from users_api.app.models.feedback import Feedback
from users_api.app.models.user import User

SOURCE = "users-api"
SPEC_VERSION = "1.0"

USER_REGISTERED = "user.registered.v1"
EMAIL_VERIFICATION_REQUESTED = "email_verification.requested.v1"
PASSWORD_RESET_REQUESTED = "password.reset_requested.v1"
PASSWORD_CHANGED = "password.changed.v1"
INVITATION_ACCEPTED = "invitation.accepted.v1"
USER_DELETED = "user.deleted.v1"
PREFERENCES_CHANGED = "preferences.changed.v1"
FEEDBACK_SUBMITTED = "feedback.submitted.v1"


@dataclass(frozen=True)
class Event:
    """A complete envelope. Its `id` is what consumers deduplicate on."""

    envelope: dict[str, Any]

    @property
    def id(self) -> uuid.UUID:
        return uuid.UUID(self.envelope["id"])

    @property
    def type(self) -> str:
        return self.envelope["type"]


def build_event(event_type: str, data: dict[str, Any], *, now: datetime) -> Event:
    return Event(
        envelope={
            "specversion": SPEC_VERSION,
            "id": str(uuid.uuid4()),
            "source": SOURCE,
            "type": event_type,
            # RFC 3339 in UTC, with the `Z` suffix the schemas' examples use.
            "time": now.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "data": data,
        }
    )


def user_registered(user: User, *, verification_url: str, now: datetime) -> Event:
    return build_event(
        USER_REGISTERED,
        {
            "user_id": str(user.id),
            "email": user.email,
            "handle": user.handle,
            "verification_url": verification_url,
        },
        now=now,
    )


def email_verification_requested(user: User, *, verification_url: str, now: datetime) -> Event:
    """A new link for an account that already exists.

    Not `user.registered` again: the account was not created twice, and
    consumers that count registrations would count it twice.
    """
    return build_event(
        EMAIL_VERIFICATION_REQUESTED,
        {"user_id": str(user.id), "email": user.email, "verification_url": verification_url},
        now=now,
    )


def invitation_accepted(invitee: User, inviter: User, *, now: datetime) -> Event:
    """An invited account proved its address, so it can follow whoever invited it.

    Carries both handles and the inviter's visibility: the consumer may not know
    either account yet, and the visibility decides whether the follow is direct
    or a request.
    """
    return build_event(
        INVITATION_ACCEPTED,
        {
            "invitee_id": str(invitee.id),
            "invitee_handle": invitee.handle,
            "inviter_id": str(inviter.id),
            "inviter_handle": inviter.handle,
            "inviter_visibility": inviter.profile_visibility.value,
        },
        now=now,
    )


def password_reset_requested(user: User, *, token: str, now: datetime) -> Event:
    return build_event(
        PASSWORD_RESET_REQUESTED,
        {"user_id": str(user.id), "email": user.email, "token": token},
        now=now,
    )


def password_changed(user: User, *, now: datetime) -> Event:
    return build_event(
        PASSWORD_CHANGED,
        {"user_id": str(user.id), "email": user.email},
        now=now,
    )


def user_deleted(user: User, *, now: datetime) -> Event:
    """An account was closed.

    `time` is the instant of the closing, not of the publication: consumers
    record it as the deletion date, so it has to be the same `now` the account
    was marked with. Nothing but the id travels: whoever cleans up after the
    account does not need to know who it was, and the schema forbids more.
    """
    return build_event(USER_DELETED, {"user_id": str(user.id)}, now=now)


def preferences_changed(user: User, *, now: datetime) -> Event:
    """An account changed its feed language or its profile visibility.

    Carries both current values and not only the one that changed, so a consumer
    that applies the event ends up with the whole preferences of the account.
    `time` is the instant the change was saved: two changes in a row can arrive
    out of order, and the consumer drops one older than the last it applied.
    """
    return build_event(
        PREFERENCES_CHANGED,
        {
            "user_id": str(user.id),
            "feed_language": user.feed_language.value,
            "profile_visibility": user.profile_visibility.value,
        },
        now=now,
    )


def feedback_submitted(feedback: Feedback) -> Event:
    """A message for the support account.

    `message` is what the user typed, so it is untrusted: whoever renders it has
    to treat it as text. `time` is the instant it was stored, not of the
    publication.
    """
    return build_event(
        FEEDBACK_SUBMITTED,
        {
            "feedback_id": str(feedback.id),
            "user_id": str(feedback.user_id),
            "handle": feedback.handle,
            "message": feedback.message,
            "device_os": feedback.device_os,
            "app_version": feedback.app_version,
        },
        now=feedback.created_at,
    )
