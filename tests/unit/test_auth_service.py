"""AuthService against doubles, with no PostgreSQL and no Redis.

These tests exist because the service only depends on interfaces. They cover
what a request through the API cannot show from outside: whether a repository
was reached at all, whether the counter was reset, whether the mail went out
with the right link.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import jwt
import pytest

from users_api.app.clients.email import EmailSender
from users_api.app.errors import ProblemError
from users_api.app.models.tokens import EmailVerificationToken
from users_api.app.models.user import User
from users_api.app.repositories.rate_limiter import RateLimiter
from users_api.app.repositories.sessions import SessionStore
from users_api.app.repositories.tokens import EmailVerificationTokenRepository
from users_api.app.repositories.users import UserRepository
from users_api.app.security import hash_password, hash_token, issue_access_token
from users_api.app.services.auth import INVALID_CREDENTIALS, AuthService
from users_api.config.settings import Settings

PASSWORD = "Contrasena1"


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
        "password_hash": hash_password(PASSWORD),
        "is_email_verified": True,
    }
    return User(**{**defaults, **overrides})


@pytest.fixture
def signing_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return Ed25519PrivateKey.generate()


@pytest.fixture
def doubles():
    users = AsyncMock(spec=UserRepository)
    users.exists_with_email_or_handle.return_value = False
    users.find_by_identifier.return_value = None
    users.find_by_email.return_value = None
    return {
        "users": users,
        "verification_tokens": AsyncMock(spec=EmailVerificationTokenRepository),
        "rate_limiter": AsyncMock(spec=RateLimiter),
        "sessions": AsyncMock(spec=SessionStore),
        "email_sender": AsyncMock(spec=EmailSender),
    }


@pytest.fixture
def service(doubles, signing_key) -> AuthService:
    doubles["rate_limiter"].count.return_value = 0
    return AuthService(settings=build_settings(), signing_key=signing_key, **doubles)


async def test_e1_h1_ca2_rejects_an_email_or_handle_already_taken(service, doubles):
    doubles["users"].exists_with_email_or_handle.return_value = True

    with pytest.raises(ProblemError) as raised:
        await service.register(email="alumno@udesa.edu.ar", handle="@alumno_01", password=PASSWORD)

    assert raised.value.status == 409
    # The account is not created, and the message does not say which of the two
    # collided.
    doubles["users"].add.assert_not_awaited()


async def test_e1_h1_ca4_stores_a_digest_and_never_the_password(service, doubles):
    doubles["users"].add.side_effect = lambda user: user

    await service.register(email="alumno@udesa.edu.ar", handle="@alumno_01", password=PASSWORD)

    stored = doubles["users"].add.await_args.args[0]
    assert stored.password_hash.startswith("$argon2")
    assert PASSWORD not in stored.password_hash


async def test_e1_h1_ca7_normalises_the_email_and_the_handle(service, doubles):
    doubles["users"].add.side_effect = lambda user: user

    await service.register(email="  Alumno@UdeSA.edu.ar ", handle="@Alumno_01", password=PASSWORD)

    stored = doubles["users"].add.await_args.args[0]
    assert stored.email == "alumno@udesa.edu.ar"
    assert stored.handle == "@alumno_01"


async def test_e1_h1_ca1_the_account_starts_unverified(service, doubles):
    doubles["users"].add.side_effect = lambda user: user

    user = await service.register(
        email="alumno@udesa.edu.ar", handle="@alumno_01", password=PASSWORD
    )

    assert user.is_email_verified is False


async def test_e1_h1_ca6_sends_a_link_whose_digest_is_what_gets_stored(service, doubles):
    doubles["users"].add.side_effect = lambda user: user

    await service.register(email="alumno@udesa.edu.ar", handle="@alumno_01", password=PASSWORD)

    sent_url = doubles["email_sender"].send_verification.await_args.kwargs["verification_url"]
    raw_token = sent_url.split("token=")[1]
    stored = doubles["verification_tokens"].add.await_args.args[0]

    # What travels in the mail is the token; what stays in the table is only its
    # digest, so a database dump is not enough to validate somebody else's
    # account.
    assert stored.token_hash == hash_token(raw_token)
    assert raw_token not in stored.token_hash


async def test_e1_h1_ca6_refuses_an_expired_link(service, doubles):
    doubles["verification_tokens"].find_by_hash.return_value = EmailVerificationToken(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        token_hash="cualquiera",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    with pytest.raises(ProblemError) as raised:
        await service.verify_email("un-token")

    assert raised.value.status == 400
    doubles["users"].update.assert_not_awaited()


async def test_e1_h1_ca6_refuses_a_link_already_used(service, doubles):
    doubles["verification_tokens"].find_by_hash.return_value = EmailVerificationToken(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        token_hash="cualquiera",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        used_at=datetime.now(UTC),
    )

    with pytest.raises(ProblemError):
        await service.verify_email("un-token")


async def test_e1_h1_ca1_a_valid_link_verifies_the_account_and_burns_the_token(service, doubles):
    token_id = uuid.uuid4()
    user = build_user(is_email_verified=False)
    doubles["verification_tokens"].find_by_hash.return_value = EmailVerificationToken(
        id=token_id,
        user_id=user.id,
        token_hash="cualquiera",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    doubles["users"].get.return_value = user

    verified = await service.verify_email("un-token")

    assert verified.is_email_verified is True
    doubles["users"].update.assert_awaited_once()
    assert doubles["verification_tokens"].mark_used.await_args.args[0] == token_id


@pytest.mark.parametrize(
    ("user", "reason"),
    [
        (None, "la cuenta no existe"),
        (build_user(is_email_verified=True), "ya esta validada"),
        (build_user(is_email_verified=False, is_suspended=True), "esta suspendida"),
    ],
)
async def test_e1_h1_ca6_resending_stays_silent_when_there_is_nothing_to_send(
    service, doubles, user, reason
):
    doubles["users"].find_by_email.return_value = user

    await service.resend_verification("alumno@udesa.edu.ar")

    # No exception and no mail: answering differently would tell an attacker
    # which addresses are registered.
    doubles["email_sender"].send_verification.assert_not_awaited()


async def test_e1_h2_ca2_a_locked_account_is_refused_before_touching_the_database(service, doubles):
    doubles["rate_limiter"].count.return_value = 5

    with pytest.raises(ProblemError) as raised:
        await service.login(identifier="alumno@udesa.edu.ar", password=PASSWORD)

    assert raised.value.status == 429
    assert raised.value.headers["Retry-After"] == str(15 * 60)
    # The point of checking the counter first: a locked account costs no query.
    doubles["users"].find_by_identifier.assert_not_awaited()


async def test_e1_h2_ca3_an_unknown_account_and_a_wrong_password_answer_the_same(service, doubles):
    doubles["users"].find_by_identifier.return_value = None
    with pytest.raises(ProblemError) as unknown:
        await service.login(identifier="nadie@udesa.edu.ar", password=PASSWORD)

    doubles["users"].find_by_identifier.return_value = build_user()
    with pytest.raises(ProblemError) as wrong_password:
        await service.login(identifier="alumno@udesa.edu.ar", password="Incorrecta1")

    assert unknown.value.status == wrong_password.value.status == 401
    assert unknown.value.detail == wrong_password.value.detail == INVALID_CREDENTIALS


async def test_e1_h2_ca2_every_failure_is_counted_even_for_accounts_that_do_not_exist(
    service, doubles
):
    with pytest.raises(ProblemError):
        await service.login(identifier="nadie@udesa.edu.ar", password=PASSWORD)

    # Counting only real accounts would turn the lockout into an oracle.
    doubles["rate_limiter"].hit.assert_awaited_once()


async def test_e1_h2_ca5_a_suspended_account_is_refused_once_the_password_is_proven(
    service, doubles
):
    doubles["users"].find_by_identifier.return_value = build_user(is_suspended=True)

    with pytest.raises(ProblemError) as raised:
        await service.login(identifier="alumno@udesa.edu.ar", password=PASSWORD)

    assert raised.value.status == 403
    assert raised.value.detail == "Cuenta suspendida"


async def test_e1_h2_ca4_an_unvalidated_account_is_pointed_at_the_mailbox(service, doubles):
    doubles["users"].find_by_identifier.return_value = build_user(is_email_verified=False)

    with pytest.raises(ProblemError) as raised:
        await service.login(identifier="alumno@udesa.edu.ar", password=PASSWORD)

    assert raised.value.status == 403
    assert "casilla de correo" in raised.value.detail


async def test_e1_h2_ca1_a_valid_login_clears_the_counter_and_returns_a_signed_token(
    service, doubles, signing_key
):
    user = build_user()
    doubles["users"].find_by_identifier.return_value = user

    token, expires_in = await service.login(identifier="alumno@udesa.edu.ar", password=PASSWORD)

    doubles["rate_limiter"].reset.assert_awaited_once()
    assert expires_in == 15 * 60

    claims = jwt.decode(token, signing_key.public_key(), algorithms=["EdDSA"])
    assert claims["sub"] == str(user.id)
    assert claims["role"] == "user"


async def test_e1_h3_ca1_logging_out_revokes_the_token_until_it_would_have_expired(
    service, doubles, signing_key
):
    token = issue_access_token(
        signing_key, subject=uuid.uuid4(), role="user", expires_in_minutes=15
    )
    claims = jwt.decode(token, signing_key.public_key(), algorithms=["EdDSA"])

    await service.logout(token)

    call = doubles["sessions"].revoke_token.await_args
    assert call.args[0] == claims["jti"]
    # Revoked exactly until its own expiry: past that instant there is nothing
    # left to remember.
    assert call.kwargs["expires_at"] == datetime.fromtimestamp(claims["exp"], tz=UTC)


async def test_e1_h3_ca1_logging_out_twice_is_not_an_error(service, doubles, signing_key):
    expired = issue_access_token(
        signing_key,
        subject=uuid.uuid4(),
        role="user",
        expires_in_minutes=15,
        now=datetime.now(UTC) - timedelta(hours=1),
    )

    # An expired token is already unusable, so revoking it changes nothing.
    await service.logout(expired)

    doubles["sessions"].revoke_token.assert_not_awaited()


async def test_e1_h3_ca1_a_malformed_token_is_rejected(service):
    with pytest.raises(ProblemError) as raised:
        await service.logout("esto-no-es-un-jwt")

    assert raised.value.status == 401
