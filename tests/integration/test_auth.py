import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from tests.integration.helpers import REGISTRATION, set_user_flag

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL"),
    reason="requires DATABASE_URL and REDIS_URL pointing at real services",
)


async def test_e1_h1_ca1_login_denied_until_account_is_verified(api):
    await api.register()

    denied = await api.login()
    assert denied.status_code == 403
    assert denied.headers["content-type"].startswith("application/problem+json")
    assert "casilla de correo" in denied.json()["detail"]

    await api.verify_last()
    assert (await api.login()).status_code == 200


async def test_e1_h1_ca2_rejects_duplicate_email(api):
    assert (await api.register()).status_code == 201
    duplicate = await api.register(handle="@otro_handle")
    assert duplicate.status_code == 409


async def test_e1_h1_ca2_rejects_malformed_email(api):
    invalid = await api.register(email="sin-arroba")
    assert invalid.status_code == 422
    assert invalid.json()["errors"][0]["field"] == "email"


async def test_e1_h1_ca3_rejects_duplicate_handle(api):
    await api.register()
    duplicate = await api.register(email="otro@udesa.edu.ar")
    assert duplicate.status_code == 409


async def test_e1_h1_ca3_rejects_handle_without_at_sign(api):
    assert (await api.register(handle="alumno_01")).status_code == 422


async def test_e1_h1_ca5_rejects_empty_required_fields(api):
    response = await api.register(handle="", password="")
    assert response.status_code == 422
    offending = {error["field"] for error in response.json()["errors"]}
    assert {"handle", "password"} <= offending


async def test_e1_h1_ca6_expired_token_is_refused_and_can_be_resent(api):
    await api.register()

    # Push the token past its window instead of waiting twenty four hours.
    async with api.app.state.engine.begin() as connection:
        await connection.execute(
            text("UPDATE email_verification_tokens SET expires_at = :past"),
            {"past": datetime.now(UTC) - timedelta(minutes=1)},
        )

    expired = await api.verify_last()
    assert expired.status_code == 400
    assert "expiró" in expired.json()["detail"]

    resent = await api.client.post(
        "/auth/resend-verification", json={"email": REGISTRATION["email"]}
    )
    assert resent.status_code == 202
    assert (await api.verify_last()).status_code == 200
    assert (await api.login()).status_code == 200


async def test_e1_h1_ca7_email_uniqueness_is_case_insensitive(api):
    assert (await api.register(email="Alumno@udesa.edu.ar")).status_code == 201
    clash = await api.register(email="alumno@udesa.edu.ar", handle="@otro_handle")
    assert clash.status_code == 409


async def test_e1_h1_ca7_login_works_with_any_capitalisation(api):
    await api.register_and_verify()
    assert (await api.login(identifier="ALUMNO@UDESA.EDU.AR")).status_code == 200


async def test_e1_h2_ca1_login_returns_a_jwt_with_expiration(api):
    import jwt

    await api.register_and_verify()
    response = await api.login()
    assert response.status_code == 200

    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 15 * 60

    claims = jwt.decode(
        body["access_token"],
        api.app.state.signing_key.public_key(),
        algorithms=["EdDSA"],
    )
    assert claims["role"] == "user"
    assert claims["handle"] == "@alumno_01"
    assert claims["exp"] - claims["iat"] == 15 * 60


async def test_e1_h2_ca1_login_also_works_with_the_handle(api):
    await api.register_and_verify()
    assert (await api.login(identifier=REGISTRATION["handle"])).status_code == 200


async def test_e1_h2_ca2_locks_the_account_after_five_failed_attempts(api):
    await api.register_and_verify()

    for _ in range(5):
        assert (await api.login(password="Incorrecta1")).status_code == 401

    locked = await api.login(password="Incorrecta1")
    assert locked.status_code == 429
    assert locked.headers["Retry-After"] == str(15 * 60)

    # The right password does not help while the window is open.
    assert (await api.login()).status_code == 429


async def test_e1_h2_ca2_a_successful_login_clears_the_counter(api):
    await api.register_and_verify()

    for _ in range(4):
        await api.login(password="Incorrecta1")
    assert (await api.login()).status_code == 200

    # Counter reset, so four more failures still do not lock the account.
    for _ in range(4):
        assert (await api.login(password="Incorrecta1")).status_code == 401


async def test_e1_h2_ca3_wrong_password_and_unknown_account_answer_the_same(api):
    await api.register_and_verify()

    wrong_password = await api.login(password="Incorrecta1")
    unknown_account = await api.login(identifier="nadie@udesa.edu.ar", password="Incorrecta1")

    assert wrong_password.status_code == unknown_account.status_code == 401
    assert wrong_password.json()["detail"] == unknown_account.json()["detail"]
    assert wrong_password.json()["detail"] == "Credenciales inválidas"


async def test_e1_h2_ca4_correct_credentials_on_unverified_account_point_to_the_mailbox(api):
    await api.register()

    response = await api.login()
    assert response.status_code == 403
    assert "casilla de correo" in response.json()["detail"]
    # The generic message is only for bad credentials; these are correct.
    assert response.json()["detail"] != "Credenciales inválidas"


async def test_e1_h2_ca5_suspended_account_is_refused(api):
    await api.register_and_verify()
    await set_user_flag(api.app, "status", "suspended")

    response = await api.login()
    assert response.status_code == 403
    assert response.json()["detail"] == "Cuenta suspendida"


async def test_e1_h2_ca5_soft_deleted_account_is_refused(api):
    await api.register_and_verify()
    await set_user_flag(api.app, "deleted_at", datetime.now(UTC))

    response = await api.login()
    assert response.status_code == 403
    assert response.json()["detail"] == "Cuenta suspendida"


async def test_e1_h2_ca5_suspension_is_not_revealed_without_the_password(api):
    await api.register_and_verify()
    await set_user_flag(api.app, "status", "suspended")

    # Wrong password on a suspended account still gets the generic message: the
    # caller has not proven they own it.
    response = await api.login(password="Incorrecta1")
    assert response.status_code == 401
    assert response.json()["detail"] == "Credenciales inválidas"


async def test_e1_h2_ca5_a_token_outliving_its_account_is_refused(api):
    await api.register_and_verify()
    token = (await api.login()).json()["access_token"]
    async with api.app.state.engine.begin() as connection:
        await connection.execute(text("DELETE FROM users"))

    response = await api.get_profile(token)
    assert response.status_code == 403
    assert response.json()["detail"] == "Cuenta suspendida"


async def test_e1_h3_ca1_token_is_revoked_on_logout(api):
    import jwt

    await api.register_and_verify()
    token = (await api.login()).json()["access_token"]

    assert (await api.logout(token)).status_code == 204

    claims = jwt.decode(
        token,
        api.app.state.signing_key.public_key(),
        algorithms=["EdDSA"],
        options={"verify_exp": False},
    )
    ttl = await api.app.state.redis.ttl(f"revoked:jti:{claims['jti']}")
    assert 0 < ttl <= 15 * 60


async def test_errors_follow_the_problem_details_format(api):
    response = await api.login(identifier="nadie@udesa.edu.ar", password="Incorrecta1")

    assert response.headers["content-type"] == "application/problem+json; charset=utf-8"
    body = response.json()
    assert set(body) >= {"type", "title", "status", "detail", "traceId", "instance"}
    assert body["status"] == 401
    assert body["instance"] == "/api/auth/login"


async def test_e1_h1_ca1_opening_the_emailed_link_verifies_the_account(api):
    """The link is built by hand, so only opening it proves the route behind it.

    It broke once already: the endpoints moved under /api and the link stayed
    where it was, pointing at a path the service no longer serves.
    """
    await api.register()

    response = await api.open_last_emailed_link()

    assert response.status_code == 200
    assert (await api.login()).status_code == 200


async def test_e1_h1_ca1_reopening_the_emailed_link_still_reports_the_account_verified(api):
    await api.register()
    await api.open_last_emailed_link()

    response = await api.open_last_emailed_link()

    assert response.status_code == 200
    assert response.json()["status"] == "verified"


async def logged_in(api) -> dict:
    await api.register_and_verify()
    response = await api.login()
    assert response.status_code == 200
    return response.json()


async def open_refresh_tokens(api) -> int:
    async with api.app.state.engine.begin() as connection:
        result = await connection.execute(
            text("SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NULL")
        )
    return result.scalar_one()


async def test_the_app_login_hands_out_a_refresh_token_and_stores_only_its_digest(api):
    body = await logged_in(api)

    assert body["refresh_token"]
    async with api.app.state.engine.begin() as connection:
        stored = (await connection.execute(text("SELECT token_hash FROM refresh_tokens"))).all()
    assert [row.token_hash for row in stored] != [body["refresh_token"]]
    assert len(stored) == 1 and len(stored[0].token_hash) == 64


async def test_refreshing_rotates_the_token_and_the_old_one_stops_working(api):
    first = await logged_in(api)

    response = await api.refresh(first["refresh_token"])

    assert response.status_code == 200
    second = response.json()
    assert set(second) >= {"access_token", "refresh_token", "token_type", "expires_in"}
    assert second["refresh_token"] != first["refresh_token"]
    assert second["expires_in"] == 15 * 60
    assert (await api.get_profile(second["access_token"])).status_code == 200
    # The new token works, the old one does not.
    assert (await api.refresh(second["refresh_token"])).status_code == 200
    replayed = await api.refresh(first["refresh_token"])
    assert replayed.status_code == 401
    assert replayed.json()["type"].endswith("/invalid-refresh-token")


async def test_an_unknown_refresh_token_is_refused_with_a_problem(api):
    response = await api.refresh("not-a-token-that-was-ever-issued")

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json; charset=utf-8"
    body = response.json()
    assert body["type"].endswith("/invalid-refresh-token")
    assert body["title"] == "No se pudo renovar la sesión"
    assert body["detail"] == "Tu sesión venció. Iniciá sesión de nuevo"
    assert body["instance"] == "/api/auth/refresh"


async def test_an_empty_refresh_token_is_a_validation_error(api):
    assert (await api.refresh("")).status_code == 422


async def test_a_refresh_token_stops_working_once_it_expires(api):
    body = await logged_in(api)
    async with api.app.state.engine.begin() as connection:
        await connection.execute(
            text("UPDATE refresh_tokens SET expires_at = now() - interval '1 second'")
        )

    response = await api.refresh(body["refresh_token"])

    assert response.status_code == 401
    assert response.json()["type"].endswith("/invalid-refresh-token")


async def test_a_refresh_token_lasts_the_configured_days(api):
    await logged_in(api)

    query = text("SELECT extract(epoch FROM expires_at - created_at) / 86400 FROM refresh_tokens")
    async with api.app.state.engine.begin() as connection:
        days = (await connection.execute(query)).scalar_one()
    assert round(float(days)) == api.app.state.settings.refresh_token_days == 7


async def test_reusing_a_refresh_token_signs_the_whole_account_out(api):
    phone = await logged_in(api)
    laptop = (await api.login()).json()
    rotated = (await api.refresh(phone["refresh_token"])).json()

    # The old token of the phone comes back.
    reused = await api.refresh(phone["refresh_token"])

    assert reused.status_code == 401
    assert reused.json()["type"].endswith("/invalid-refresh-token")
    # Committed, not rolled back with the 401: nothing of the account is open.
    assert await open_refresh_tokens(api) == 0
    assert (await api.refresh(rotated["refresh_token"])).status_code == 401
    assert (await api.refresh(laptop["refresh_token"])).status_code == 401
    # And the access tokens already out stop working too.
    revoked = await api.get_profile(rotated["access_token"])
    assert revoked.status_code == 401
    assert revoked.json()["type"].endswith("/session-revoked")
    assert (await api.get_profile(laptop["access_token"])).status_code == 401


async def test_only_one_of_two_simultaneous_refreshes_wins(api):
    import asyncio

    body = await logged_in(api)

    first, second = await asyncio.gather(
        api.refresh(body["refresh_token"]), api.refresh(body["refresh_token"])
    )

    assert sorted([first.status_code, second.status_code]) == [200, 401]


async def test_logging_out_with_the_refresh_token_leaves_it_unusable(api):
    body = await logged_in(api)

    assert (await api.logout(body["access_token"], body["refresh_token"])).status_code == 204

    refused = await api.refresh(body["refresh_token"])
    assert refused.status_code == 401
    assert refused.json()["type"].endswith("/invalid-refresh-token")


async def test_logging_out_without_a_body_still_works_and_keeps_the_refresh_token(api):
    body = await logged_in(api)

    assert (await api.logout(body["access_token"])).status_code == 204

    assert (await api.refresh(body["refresh_token"])).status_code == 200


async def test_logging_out_leaves_the_refresh_token_of_another_device_alone(api):
    phone = await logged_in(api)
    laptop = (await api.login()).json()

    await api.logout(phone["access_token"], phone["refresh_token"])

    assert (await api.refresh(laptop["refresh_token"])).status_code == 200


async def test_logging_out_ignores_a_refresh_token_nobody_issued(api):
    body = await logged_in(api)

    response = await api.logout(body["access_token"], "not-a-token-that-was-ever-issued")

    assert response.status_code == 204
    assert (await api.refresh(body["refresh_token"])).status_code == 200


async def test_logging_out_ignores_the_refresh_token_of_another_account(api):
    mine = await logged_in(api)
    await api.register_and_verify(email="otra@udesa.edu.ar", handle="@otra_02")
    theirs = (await api.login(identifier="otra@udesa.edu.ar")).json()

    assert (await api.logout(mine["access_token"], theirs["refresh_token"])).status_code == 204

    assert (await api.refresh(theirs["refresh_token"])).status_code == 200


async def test_logging_out_with_an_expired_access_token_still_closes_the_refresh_family(api):
    import jwt

    from users_api.app.security import issue_access_token

    body = await logged_in(api)
    claims = jwt.decode(
        body["access_token"], api.app.state.signing_key.public_key(), algorithms=["EdDSA"]
    )
    expired = issue_access_token(
        api.app.state.signing_key,
        subject=claims["sub"],
        role=claims["role"],
        handle=claims["handle"],
        profile_visibility=claims["profile_visibility"],
        expires_in_minutes=15,
        issuer=api.app.state.settings.jwt_issuer,
        now=datetime.now(UTC) - timedelta(hours=1),
    )

    assert (await api.logout(expired, body["refresh_token"])).status_code == 204

    assert (await api.refresh(body["refresh_token"])).status_code == 401


@pytest.mark.parametrize(
    ("status", "code"),
    [("suspended", "account-suspended"), ("under_review", "account-under-review")],
)
async def test_a_blocked_account_cannot_refresh_its_session(api, status, code):
    body = await logged_in(api)
    await set_user_flag(api.app, "status", status)

    response = await api.refresh(body["refresh_token"])

    assert response.status_code == 403
    assert response.json()["type"].endswith(f"/{code}")
    assert response.json()["title"] == "No se pudo renovar la sesión"
    # The refusal rolled the consumption back: nothing was spent, and nothing
    # new was handed out.
    await set_user_flag(api.app, "status", "active")
    assert (await api.refresh(body["refresh_token"])).status_code == 200


async def test_a_refresh_token_of_a_deleted_account_is_refused(api):
    body = await logged_in(api)
    async with api.app.state.engine.begin() as connection:
        await connection.execute(text("UPDATE users SET deleted_at = now()"))

    response = await api.refresh(body["refresh_token"])

    assert response.status_code == 403
    assert response.json()["type"].endswith("/account-suspended")
