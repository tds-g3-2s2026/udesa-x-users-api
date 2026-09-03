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


async def test_e1_h1_ca6_token_cannot_be_reused(api):
    await api.register()
    token = api.last_emailed_token()

    assert (await api.client.post("/auth/verify", json={"token": token})).status_code == 200
    assert (await api.client.post("/auth/verify", json={"token": token})).status_code == 400


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
    await set_user_flag(api.app, "is_suspended", True)

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
    await set_user_flag(api.app, "is_suspended", True)

    # Wrong password on a suspended account still gets the generic message: the
    # caller has not proven they own it.
    response = await api.login(password="Incorrecta1")
    assert response.status_code == 401
    assert response.json()["detail"] == "Credenciales inválidas"


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

    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert set(body) >= {"type", "title", "status", "detail", "traceId", "instance"}
    assert body["status"] == 401
    assert body["instance"] == "/auth/login"
