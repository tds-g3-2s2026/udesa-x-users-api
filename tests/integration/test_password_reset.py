import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from tests.integration.helpers import REGISTRATION

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("REDIS_URL"),
    reason="requires DATABASE_URL and REDIS_URL pointing at real services",
)

NEW_PASSWORD = "Contrasena2"


async def expire_reset_tokens(app) -> None:
    """Push the reset window into the past instead of waiting ten minutes."""
    async with app.state.engine.begin() as connection:
        await connection.execute(
            text("UPDATE password_reset_tokens SET expires_at = :past"),
            {"past": datetime.now(UTC) - timedelta(minutes=1)},
        )


async def request_reset(api, identifier=REGISTRATION["email"]) -> str:
    """Ask for a link and return the token that went out by mail."""
    assert (await api.forgot_password(identifier)).status_code == 202
    return api.last_emailed_token()


# --- ventana de diez minutos del link -----------------------------------------


async def test_e1_h5_ca1_reset_link_expires_after_ten_minutes(api):
    await api.register_and_verify()
    token = await request_reset(api)

    # Ten minutes, not the twenty four hours of the verification link. The
    # margin absorbs the clock skew between Python, which computes expires_at,
    # and PostgreSQL, which stamps created_at on insert.
    async with api.app.state.engine.begin() as connection:
        window = await connection.scalar(
            text("SELECT expires_at - created_at FROM password_reset_tokens")
        )
    assert abs(window - timedelta(minutes=10)) < timedelta(seconds=5)

    await expire_reset_tokens(api.app)
    expired = await api.reset_password(token, NEW_PASSWORD)
    assert expired.status_code == 400

    # The old password still works: an expired link changes nothing.
    assert (await api.login()).status_code == 200


# --- link vencido y pedido de uno nuevo ---------------------------------------


async def test_e1_h5_ca2_expired_link_is_refused_and_can_be_resent(api):
    await api.register_and_verify()
    token = await request_reset(api)
    await expire_reset_tokens(api.app)

    expired = await api.reset_password(token, NEW_PASSWORD)
    assert expired.status_code == 400
    assert expired.headers["content-type"].startswith("application/problem+json")
    assert "Pedí uno nuevo" in expired.json()["detail"]

    # And asking for another one works, which is what the app offers next.
    fresh_token = await request_reset(api)
    assert (await api.reset_password(fresh_token, NEW_PASSWORD)).status_code == 200
    assert (await api.login(password=NEW_PASSWORD)).status_code == 200


# --- respuesta generica ante cualquier identificador --------------------------


async def test_e1_h5_ca4_unknown_account_gets_the_same_generic_answer(api):
    await api.register_and_verify()

    registered = await api.forgot_password(REGISTRATION["email"])
    unknown = await api.forgot_password("nadie@udesa.edu.ar")

    assert registered.status_code == unknown.status_code == 202
    assert registered.json() == unknown.json()


# --- link de un solo uso ------------------------------------------------------


async def test_e1_h5_ca5_reset_token_cannot_be_reused(api):
    await api.register_and_verify()
    token = await request_reset(api)

    assert (await api.reset_password(token, NEW_PASSWORD)).status_code == 200
    assert (await api.reset_password(token, "Contrasena3")).status_code == 400

    # The second attempt changed nothing: the password is still the first one.
    assert (await api.login(password=NEW_PASSWORD)).status_code == 200


async def test_e1_h5_ca5_using_one_link_kills_the_other_open_ones(api):
    await api.register_and_verify()
    first_token = await request_reset(api)
    second_token = await request_reset(api)

    assert (await api.reset_password(second_token, NEW_PASSWORD)).status_code == 200
    # The older link was never used, but it must not be a way in any more.
    assert (await api.reset_password(first_token, "Contrasena3")).status_code == 400


# --- contrasena nueva distinta de la actual -----------------------------------


async def test_e1_h5_ca6_rejects_reusing_the_current_password(api):
    await api.register_and_verify()
    token = await request_reset(api)

    repeated = await api.reset_password(token, REGISTRATION["password"])
    assert repeated.status_code == 400
    assert "distinta de la actual" in repeated.json()["detail"]


# --- revocacion de todas las sesiones -----------------------------------------


async def test_e1_h5_ca7_successful_reset_revokes_every_active_session(api):
    import jwt

    await api.register_and_verify()
    access_token = (await api.login()).json()["access_token"]
    claims = jwt.decode(
        access_token,
        api.app.state.signing_key.public_key(),
        algorithms=["EdDSA"],
        options={"verify_exp": False},
    )

    token = await request_reset(api)
    assert (await api.reset_password(token, NEW_PASSWORD)).status_code == 200

    # Every token issued before this instant is revoked at once: the sessions
    # were never stored, so what is recorded is the cutoff, not each jti.
    key = f"revoked:user:{claims['sub']}"
    revoked_at = await api.app.state.redis.get(key)
    assert revoked_at is not None
    assert int(revoked_at) >= claims["iat"]

    ttl = await api.app.state.redis.ttl(key)
    assert 0 < ttl <= 15 * 60


# --- limite de pedidos por identificador --------------------------------------


async def test_e1_h5_ca8_limits_reset_requests_for_the_same_email(api):
    await api.register_and_verify()

    for _ in range(3):
        assert (await api.forgot_password()).status_code == 202

    blocked = await api.forgot_password()
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == str(60 * 60)


async def test_e1_h5_ca8_the_limit_also_counts_accounts_that_do_not_exist(api):
    # Otherwise the limit itself would answer which addresses are registered:
    # the fourth request would only be refused for the real ones.
    for _ in range(3):
        assert (await api.forgot_password("nadie@udesa.edu.ar")).status_code == 202

    blocked = await api.forgot_password("nadie@udesa.edu.ar")
    assert blocked.status_code == 429
