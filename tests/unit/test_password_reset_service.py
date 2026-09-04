"""PasswordResetService against doubles, with no PostgreSQL and no Redis."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from users_api.app.clients.email import EmailSender
from users_api.app.errors import ProblemError
from users_api.app.models.tokens import PasswordResetToken
from users_api.app.models.user import User
from users_api.app.repositories.rate_limiter import RateLimiter
from users_api.app.repositories.sessions import SessionStore
from users_api.app.repositories.tokens import PasswordResetTokenRepository
from users_api.app.repositories.users import UserRepository
from users_api.app.security import hash_password, hash_token, verify_password
from users_api.app.services.password_reset import PasswordResetService
from users_api.config.settings import Settings

CURRENT_PASSWORD = "Contrasena1"
NEW_PASSWORD = "Contrasena2"


def build_settings(**overrides) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://unused",
        redis_url="redis://unused",
        **overrides,
    )


def build_user(**overrides) -> User:
    defaults = {
        "id": uuid.uuid4(),
        "email": "alumno@udesa.edu.ar",
        "handle": "@alumno_01",
        "password_hash": hash_password(CURRENT_PASSWORD),
        "is_email_verified": True,
    }
    return User(**{**defaults, **overrides})


def build_token(user_id: uuid.UUID, **overrides) -> PasswordResetToken:
    defaults = {
        "id": uuid.uuid4(),
        "user_id": user_id,
        "token_hash": hash_token("un-token"),
        "expires_at": datetime.now(UTC) + timedelta(minutes=5),
    }
    return PasswordResetToken(**{**defaults, **overrides})


@pytest.fixture
def doubles():
    users = AsyncMock(spec=UserRepository)
    users.find_by_identifier.return_value = None
    rate_limiter = AsyncMock(spec=RateLimiter)
    rate_limiter.hit.return_value = 1
    return {
        "users": users,
        "reset_tokens": AsyncMock(spec=PasswordResetTokenRepository),
        "rate_limiter": rate_limiter,
        "sessions": AsyncMock(spec=SessionStore),
        "email_sender": AsyncMock(spec=EmailSender),
    }


@pytest.fixture
def service(doubles) -> PasswordResetService:
    return PasswordResetService(settings=build_settings(), **doubles)


async def test_e1_h5_ca8_the_cap_is_counted_before_looking_the_account_up(service, doubles):
    doubles["rate_limiter"].hit.return_value = 4

    with pytest.raises(ProblemError) as raised:
        await service.forgot_password("alumno@udesa.edu.ar")

    assert raised.value.status == 429
    # Counting after resolving the account would make the 429 itself answer
    # whether that address is registered.
    doubles["users"].find_by_identifier.assert_not_awaited()


async def test_e1_h5_ca8_the_request_is_counted_even_for_addresses_that_do_not_exist(
    service, doubles
):
    await service.forgot_password("nadie@udesa.edu.ar")

    doubles["rate_limiter"].hit.assert_awaited_once()


@pytest.mark.parametrize(
    ("user", "reason"),
    [
        (None, "la cuenta no existe"),
        (build_user(is_suspended=True), "esta suspendida"),
    ],
)
async def test_e1_h5_ca4_nothing_is_sent_and_nothing_is_revealed(service, doubles, user, reason):
    doubles["users"].find_by_identifier.return_value = user

    await service.forgot_password("alumno@udesa.edu.ar")

    doubles["email_sender"].send_password_reset.assert_not_awaited()
    doubles["reset_tokens"].add.assert_not_awaited()


async def test_e1_h5_ca1_the_link_lasts_the_configured_ten_minutes(service, doubles):
    doubles["users"].find_by_identifier.return_value = build_user()
    before = datetime.now(UTC)

    await service.forgot_password("alumno@udesa.edu.ar")

    after = datetime.now(UTC)
    stored = doubles["reset_tokens"].add.await_args.args[0]
    # Bounded on both ends: the service reads the clock somewhere between these
    # two instants, so this pins the ten minutes without depending on how long
    # the call took.
    assert before + timedelta(minutes=10) <= stored.expires_at <= after + timedelta(minutes=10)


async def test_e1_h5_ca1_the_mail_carries_the_token_and_the_table_only_its_digest(service, doubles):
    doubles["users"].find_by_identifier.return_value = build_user()

    await service.forgot_password("alumno@udesa.edu.ar")

    sent_url = doubles["email_sender"].send_password_reset.await_args.kwargs["reset_url"]
    raw_token = sent_url.split("token=")[1]
    stored = doubles["reset_tokens"].add.await_args.args[0]
    assert stored.token_hash == hash_token(raw_token)


@pytest.mark.parametrize(
    ("token", "reason"),
    [
        (None, "el link no existe"),
        ("expired", "el link vencio"),
        ("used", "el link ya se uso"),
    ],
)
async def test_e1_h5_ca5_an_unusable_link_is_refused_the_same_way(service, doubles, token, reason):
    user_id = uuid.uuid4()
    stored = {
        None: None,
        "expired": build_token(user_id, expires_at=datetime.now(UTC) - timedelta(minutes=1)),
        "used": build_token(user_id, used_at=datetime.now(UTC)),
    }[token]
    doubles["reset_tokens"].find_by_hash.return_value = stored

    with pytest.raises(ProblemError) as raised:
        await service.reset_password("un-token", NEW_PASSWORD)

    assert raised.value.status == 400
    doubles["users"].update.assert_not_awaited()


async def test_e1_h5_ca6_the_new_password_cannot_be_the_current_one(service, doubles):
    user = build_user()
    doubles["reset_tokens"].find_by_hash.return_value = build_token(user.id)
    doubles["users"].get.return_value = user

    with pytest.raises(ProblemError) as raised:
        await service.reset_password("un-token", CURRENT_PASSWORD)

    assert raised.value.status == 400
    doubles["users"].update.assert_not_awaited()


async def test_e1_h5_ca3_the_stored_digest_is_replaced_by_the_new_one(service, doubles):
    user = build_user()
    doubles["reset_tokens"].find_by_hash.return_value = build_token(user.id)
    doubles["users"].get.return_value = user

    await service.reset_password("un-token", NEW_PASSWORD)

    updated = doubles["users"].update.await_args.args[0]
    assert verify_password(NEW_PASSWORD, updated.password_hash)
    assert not verify_password(CURRENT_PASSWORD, updated.password_hash)


async def test_e1_h5_ca5_using_one_link_closes_every_other_open_link(service, doubles):
    user = build_user()
    doubles["reset_tokens"].find_by_hash.return_value = build_token(user.id)
    doubles["users"].get.return_value = user

    await service.reset_password("un-token", NEW_PASSWORD)

    # One sent minutes earlier would otherwise still be a way in after the
    # password already changed.
    assert doubles["reset_tokens"].mark_all_used.await_args.args[0] == user.id


async def test_e1_h5_ca7_a_successful_reset_revokes_every_open_session(service, doubles):
    user = build_user()
    doubles["reset_tokens"].find_by_hash.return_value = build_token(user.id)
    doubles["users"].get.return_value = user

    await service.reset_password("un-token", NEW_PASSWORD)

    call = doubles["sessions"].revoke_all.await_args
    assert call.args[0] == user.id
    assert call.kwargs["ttl_seconds"] == 15 * 60
