"""Change a password by proving knowledge of the current password.

This is the authenticated counterpart of email recovery: it changes how account
ownership is proven, not what happens afterward. These tests cover the current
password, lockout, and email notification; password policy and revocation are
covered by the other flow.
"""

import os

import pytest

from tests.integration.helpers import REGISTRATION

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL"),
    reason="requires DATABASE_URL and REDIS_URL pointing at real services",
)

CURRENT_PASSWORD = REGISTRATION["password"]
NEW_PASSWORD = "Contrasena2"


async def signed_in(api) -> str:
    """A usable account and an active session token."""
    await api.register_and_verify()
    return (await api.login()).json()["access_token"]


async def test_change_password_rejects_a_weak_or_repeated_password(api):
    token = await signed_in(api)

    weak = await api.change_password(token, CURRENT_PASSWORD, "minuscula")
    assert weak.status_code == 422
    assert [problem["field"] for problem in weak.json()["errors"]] == ["password"]

    # The same rule as password recovery, with the same error identifier.
    repeated = await api.change_password(token, CURRENT_PASSWORD, CURRENT_PASSWORD)
    assert repeated.status_code == 400
    assert repeated.json()["type"].endswith("/password-unchanged")

    # Neither attempt changed the password.
    assert (await api.login()).status_code == 200


async def test_change_password_revokes_every_session_including_the_current_one(api):
    token = await signed_in(api)
    # A second session, as if it were from another device.
    other_device = (await api.login()).json()["access_token"]

    changed = await api.change_password(token, CURRENT_PASSWORD, NEW_PASSWORD)
    assert changed.status_code == 200
    assert changed.json() == {"status": "changed"}

    # The session that made the change stops working immediately.
    reused = await api.change_password(token, NEW_PASSWORD, "Contrasena3")
    assert reused.status_code == 401
    assert reused.json()["type"].endswith("/session-revoked")

    # The other device's session is revoked too.
    assert (await api.change_password(other_device, NEW_PASSWORD, "Contrasena3")).status_code == 401

    # Signing in again requires the new password.
    assert (await api.login()).status_code == 401
    assert (await api.login(password=NEW_PASSWORD)).status_code == 200


async def test_change_password_locks_the_account_after_three_wrong_current_passwords(api):
    token = await signed_in(api)

    for _ in range(3):
        wrong = await api.change_password(token, "Incorrecta1", NEW_PASSWORD)
        assert wrong.status_code == 400
        assert wrong.json()["type"].endswith("/invalid-current-password")

    # On the fourth attempt, even the correct password is rejected.
    blocked = await api.change_password(token, CURRENT_PASSWORD, NEW_PASSWORD)
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == str(15 * 60)

    # This endpoint has its own identifier instead of login's `too-many-attempts`:
    # the failures and their counters differ, and clients route by the last
    # segment of `type`. The text does not say the account is locked because it
    # is not.
    assert blocked.json()["type"].endswith("/too-many-password-attempts")
    assert "cuenta quedó bloqueada" not in blocked.json()["detail"]

    # This endpoint has its own counter: failures here must not prevent login,
    # which could otherwise let someone lock another account with brief access
    # to an unlocked phone.
    assert (await api.login()).status_code == 200


async def test_change_password_sends_a_notification_email(api):
    token = await signed_in(api)
    api.caplog.clear()

    assert (await api.change_password(token, CURRENT_PASSWORD, NEW_PASSWORD)).status_code == 200

    assert "la contraseña de la cuenta fue modificada" in api.caplog.text
    assert REGISTRATION["email"].lower() in api.caplog.text


async def test_the_notification_is_not_sent_when_the_change_fails(api):
    token = await signed_in(api)
    api.caplog.clear()

    assert (await api.change_password(token, "Incorrecta1", NEW_PASSWORD)).status_code == 400

    assert "fue modificada" not in api.caplog.text
