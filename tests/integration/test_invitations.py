"""Registering through somebody's invitation link, and what verifying it announces."""

import os
import uuid

import pytest
from sqlalchemy import select

from tests.integration.helpers import REGISTRATION
from tests.schemas import validator_for
from users_api.infrastructure.database.models import UserModel

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL") or not os.getenv("RABBITMQ_URL"),
    reason="requires DATABASE_URL, REDIS_URL and RABBITMQ_URL pointing at real services",
)

INVITEE = {"email": "invitada@udesa.edu.ar", "handle": "@invitada_01"}
EVENT = "invitation.accepted.v1"


async def verified_inviter(api) -> str:
    """The id a link would carry: a verified account that can sign in."""
    await api.register_and_verify()
    token = (await api.login()).json()["access_token"]
    return (await api.get_profile(token)).json()["id"]


async def invited_by(api, email: str) -> uuid.UUID | None:
    async with api.app.state.engine.connect() as connection:
        return await connection.scalar(
            select(UserModel.invited_by_id).where(UserModel.email == email)
        )


async def accepted_events(api) -> list[dict]:
    return [event for event in await api.outbox_events() if event["type"] == EVENT]


async def test_e3_h9_ca1_the_link_carries_the_referral_code(api):
    inviter_id = await verified_inviter(api)

    response = await api.register(**INVITEE, ref=inviter_id)

    assert response.status_code == 201
    assert str(await invited_by(api, INVITEE["email"])) == inviter_id


async def test_e3_h9_ca2_a_verified_invitee_publishes_invitation_accepted(api):
    inviter_id = await verified_inviter(api)
    registered = await api.register(**INVITEE, ref=inviter_id)
    assert await accepted_events(api) == []

    assert (await api.verify_last()).status_code == 200

    (event,) = await accepted_events(api)
    validator_for(EVENT).validate(event)
    assert event["data"] == {
        "invitee_id": registered.json()["id"],
        "invitee_handle": INVITEE["handle"],
        "inviter_id": inviter_id,
        "inviter_handle": REGISTRATION["handle"],
        "inviter_visibility": "public",
    }


async def test_e3_h9_ca2_the_event_carries_a_protected_inviters_visibility(api):
    inviter_id = await verified_inviter(api)
    token = (await api.login()).json()["access_token"]
    await api.update_preferences(token, profile_visibility="protected")
    await api.register(**INVITEE, ref=inviter_id)

    await api.verify_last()

    (event,) = await accepted_events(api)
    assert event["data"]["inviter_visibility"] == "protected"


async def test_e3_h9_ca2_a_second_link_of_the_same_account_does_not_repeat_the_event(api):
    inviter_id = await verified_inviter(api)
    await api.register(**INVITEE, ref=inviter_id)
    first_token = await api.last_token()
    await api.client.post("/auth/resend-verification", json={"email": INVITEE["email"]})
    second_token = await api.last_token()

    for token in (first_token, second_token):
        assert (await api.client.post("/auth/verify", json={"token": token})).status_code == 200

    assert len(await accepted_events(api)) == 1


@pytest.mark.parametrize("ref", [str(uuid.uuid4()), "not-a-uuid", ""])
async def test_a_link_that_leads_nowhere_still_registers_the_account(api, ref):
    response = await api.register(**INVITEE, ref=ref)

    assert response.status_code == 201
    assert await invited_by(api, INVITEE["email"]) is None
    await api.verify_last()
    assert await accepted_events(api) == []


async def test_a_registration_without_a_link_announces_nothing(api):
    await api.register(**INVITEE)

    await api.verify_last()

    assert await accepted_events(api) == []


async def test_a_closed_inviter_is_not_recorded(api):
    inviter_id = await verified_inviter(api)
    token = (await api.login()).json()["access_token"]
    await api.delete_account(token, REGISTRATION["password"])

    response = await api.register(**INVITEE, ref=inviter_id)

    assert response.status_code == 201
    assert await invited_by(api, INVITEE["email"]) is None


async def test_an_inviter_closed_before_the_invitee_verifies_is_not_announced(api):
    inviter_id = await verified_inviter(api)
    token = (await api.login()).json()["access_token"]
    await api.register(**INVITEE, ref=inviter_id)
    verification_token = await api.last_token()
    await api.delete_account(token, REGISTRATION["password"])

    verified = await api.client.post("/auth/verify", json={"token": verification_token})

    assert verified.status_code == 200
    assert await accepted_events(api) == []
