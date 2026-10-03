"""Refresh tokens through AuthService, against an in-memory repository.

The repository is a real fake and not a mock: what these tests check is how a
chain of tokens behaves over several calls (rotation, reuse, logout), and a mock
would only record that the service called it. The atomicity of `consume` is a
property of the SQL statement and is covered by the integration suite.
"""

import dataclasses
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import jwt
import pytest

from users_api.app.clients.email import EmailSender
from users_api.app.errors import ProblemError
from users_api.app.models.tokens import RefreshToken
from users_api.app.models.user import AccountStatus, Role, User
from users_api.app.repositories.rate_limiter import RateLimiter
from users_api.app.repositories.sessions import SessionStore
from users_api.app.repositories.tokens import (
    EmailVerificationTokenRepository,
    RefreshTokenRepository,
)
from users_api.app.repositories.users import UserRepository
from users_api.app.security import hash_password, hash_token, issue_access_token
from users_api.app.services.auth import (
    AuthService,
    InvalidRefreshTokenError,
    ReusedRefreshTokenError,
)
from users_api.config.settings import Settings

PASSWORD = "Contrasena1"


class InMemoryRefreshTokens(RefreshTokenRepository):
    def __init__(self) -> None:
        self.rows: list[RefreshToken] = []

    async def add(self, token: RefreshToken) -> None:
        self.rows.append(dataclasses.replace(token, id=uuid.uuid4()))

    async def find_by_hash(self, token_hash: str) -> RefreshToken | None:
        return next((row for row in self.rows if row.token_hash == token_hash), None)

    async def consume(self, token_hash: str, *, now: datetime) -> RefreshToken | None:
        # The same four conditions the SQL statement puts in its WHERE.
        for row in self.rows:
            if (
                row.token_hash == token_hash
                and row.used_at is None
                and row.revoked_at is None
                and row.expires_at > now
            ):
                row.used_at = now
                return dataclasses.replace(row)
        return None

    async def revoke_family(self, family_id: uuid.UUID, *, revoked_at: datetime) -> None:
        for row in self.rows:
            if row.family_id == family_id and row.revoked_at is None:
                row.revoked_at = revoked_at

    async def revoke_all(self, user_id: uuid.UUID, *, revoked_at: datetime) -> None:
        for row in self.rows:
            if row.user_id == user_id and row.revoked_at is None:
                row.revoked_at = revoked_at


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
def user() -> User:
    return build_user()


@pytest.fixture
def tokens() -> InMemoryRefreshTokens:
    return InMemoryRefreshTokens()


@pytest.fixture
def users(user) -> AsyncMock:
    repository = AsyncMock(spec=UserRepository)
    repository.find_by_identifier.return_value = user
    repository.get.return_value = user
    return repository


@pytest.fixture
def sessions() -> AsyncMock:
    return AsyncMock(spec=SessionStore)


@pytest.fixture
def service(users, tokens, sessions, signing_key) -> AuthService:
    rate_limiter = AsyncMock(spec=RateLimiter)
    rate_limiter.count.return_value = 0
    return AuthService(
        users=users,
        verification_tokens=AsyncMock(spec=EmailVerificationTokenRepository),
        refresh_tokens=tokens,
        rate_limiter=rate_limiter,
        sessions=sessions,
        settings=Settings(
            database_url="postgresql+asyncpg://unused",
            redis_url="redis://unused",
        ),
        signing_key=signing_key,
        email_sender=AsyncMock(spec=EmailSender),
    )


async def log_in(service, identifier: str = "alumno@udesa.edu.ar"):
    return await service.login(identifier=identifier, password=PASSWORD)


async def test_login_hands_out_a_refresh_token_and_stores_only_its_digest(service, tokens, user):
    before = datetime.now(UTC)

    session = await log_in(service)

    (stored,) = tokens.rows
    assert stored.user_id == user.id
    assert stored.token_hash == hash_token(session.refresh_token)
    assert stored.token_hash != session.refresh_token
    assert stored.used_at is None and stored.revoked_at is None
    # A week, from REFRESH_TOKEN_DAYS.
    assert timedelta(days=7) <= stored.expires_at - before < timedelta(days=7, minutes=1)


async def test_each_login_starts_a_family_of_its_own(service, tokens):
    await log_in(service)
    await log_in(service)

    assert len({row.family_id for row in tokens.rows}) == 2


async def test_the_admin_login_hands_out_no_refresh_token(service, tokens, users):
    users.find_by_email.return_value = build_user(role=Role.SUPERADMIN)

    await service.admin_login(email="alumno@udesa.edu.ar", password=PASSWORD)

    assert tokens.rows == []


async def test_refreshing_rotates_the_token_inside_its_family(service, tokens, signing_key):
    first = await log_in(service)

    second = await service.refresh(first.refresh_token)

    assert second.refresh_token != first.refresh_token
    assert second.access_token
    assert second.expires_in == 15 * 60
    assert len({row.family_id for row in tokens.rows}) == 1
    # The new token keeps working and rotates in turn.
    third = await service.refresh(second.refresh_token)
    assert third.refresh_token not in (first.refresh_token, second.refresh_token)


async def test_a_token_that_was_already_exchanged_is_refused(service):
    first = await log_in(service)
    await service.refresh(first.refresh_token)

    with pytest.raises(InvalidRefreshTokenError) as raised:
        await service.refresh(first.refresh_token)

    assert raised.value.status == 401
    assert raised.value.code == "invalid-refresh-token"
    assert raised.value.title == "No se pudo renovar la sesión"
    assert raised.value.detail == "Tu sesión venció. Iniciá sesión de nuevo"


async def test_an_unknown_token_is_refused_and_revokes_nothing(service, tokens, sessions):
    await log_in(service)

    with pytest.raises(InvalidRefreshTokenError) as raised:
        await service.refresh("not-a-token-that-was-ever-issued")

    assert not isinstance(raised.value, ReusedRefreshTokenError)
    assert all(row.revoked_at is None for row in tokens.rows)
    sessions.revoke_all.assert_not_awaited()


async def test_a_token_stops_working_after_seven_days(service, tokens, sessions):
    session = await log_in(service)
    # Seven days and a second later: the same as the clock moving forward.
    tokens.rows[0].expires_at = datetime.now(UTC) - timedelta(seconds=1)

    with pytest.raises(InvalidRefreshTokenError) as raised:
        await service.refresh(session.refresh_token)

    # Expired is not reused: nothing else is touched.
    assert not isinstance(raised.value, ReusedRefreshTokenError)
    sessions.revoke_all.assert_not_awaited()


async def test_reusing_a_token_revokes_every_session_of_the_account(
    service, tokens, sessions, user
):
    phone = await log_in(service)
    laptop = await log_in(service)
    rotated = await service.refresh(phone.refresh_token)

    # The old token of the phone comes back: somebody kept a copy.
    with pytest.raises(ReusedRefreshTokenError) as raised:
        await service.refresh(phone.refresh_token)

    assert raised.value.code == "invalid-refresh-token"
    # The whole account, not just the phone's family: the laptop's token and the
    # one the phone just rotated into die too.
    assert all(row.revoked_at is not None for row in tokens.rows)
    for survivor in (laptop.refresh_token, rotated.refresh_token):
        with pytest.raises(InvalidRefreshTokenError):
            await service.refresh(survivor)
    # And the access tokens already handed out, for as long as they could live.
    sessions.revoke_all.assert_awaited_once()
    call = sessions.revoke_all.await_args
    assert call.args == (user.id,)
    assert call.kwargs["ttl_seconds"] == 15 * 60
    assert isinstance(call.kwargs["now"], datetime)


async def test_reusing_a_token_does_not_touch_other_accounts(service, tokens, users):
    other = build_user(id=uuid.uuid4(), email="otra@udesa.edu.ar", handle="@otra_02")
    mine = await log_in(service)
    users.find_by_identifier.return_value = other
    theirs = await log_in(service, identifier="otra@udesa.edu.ar")
    await service.refresh(mine.refresh_token)

    with pytest.raises(ReusedRefreshTokenError):
        await service.refresh(mine.refresh_token)

    survivors = [row for row in tokens.rows if row.revoked_at is None]
    assert [row.token_hash for row in survivors] == [hash_token(theirs.refresh_token)]


async def test_a_replay_after_the_revocation_does_not_sign_the_owner_out_again(service, sessions):
    first = await log_in(service)
    await service.refresh(first.refresh_token)
    with pytest.raises(ReusedRefreshTokenError):
        await service.refresh(first.refresh_token)

    # The account is already closed down; the old copy now is just a bad token.
    with pytest.raises(InvalidRefreshTokenError) as raised:
        await service.refresh(first.refresh_token)

    assert not isinstance(raised.value, ReusedRefreshTokenError)
    sessions.revoke_all.assert_awaited_once()


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"status": AccountStatus.SUSPENDED}, "account-suspended"),
        ({"status": AccountStatus.UNDER_REVIEW}, "account-under-review"),
        ({"deleted_at": datetime(2026, 1, 1, tzinfo=UTC)}, "account-suspended"),
    ],
)
async def test_a_blocked_account_cannot_refresh(service, tokens, user, changes, code):
    session = await log_in(service)
    rows_before = len(tokens.rows)
    for name, value in changes.items():
        setattr(user, name, value)

    with pytest.raises(ProblemError) as raised:
        await service.refresh(session.refresh_token)

    assert raised.value.status == 403
    assert raised.value.code == code
    assert raised.value.title == "No se pudo renovar la sesión"
    # No new token was handed out.
    assert len(tokens.rows) == rows_before


async def test_an_account_whose_temporary_password_expired_cannot_refresh(service, tokens, user):
    session = await log_in(service)
    user.must_change_password = True
    user.temporary_password_expires_at = datetime.now(UTC) - timedelta(minutes=1)

    with pytest.raises(ProblemError) as raised:
        await service.refresh(session.refresh_token)

    assert raised.value.status == 403
    assert raised.value.code == "temporary-password-expired"
    assert raised.value.title == "No se pudo renovar la sesión"


async def test_a_token_whose_account_no_longer_exists_is_refused_like_any_invalid_token(
    service, users
):
    session = await log_in(service)
    users.get.return_value = None

    with pytest.raises(InvalidRefreshTokenError):
        await service.refresh(session.refresh_token)


async def test_the_refreshed_access_token_carries_the_current_state_of_the_account(
    service, user, signing_key
):
    session = await log_in(service)
    user.handle = "@renombrado"

    refreshed = await service.refresh(session.refresh_token)

    claims = jwt.decode(refreshed.access_token, signing_key.public_key(), algorithms=["EdDSA"])
    assert claims["sub"] == str(user.id)
    assert claims["handle"] == "@renombrado"


async def test_logging_out_with_the_refresh_token_leaves_it_unusable(service, sessions):
    session = await log_in(service)

    await service.logout(session.access_token, session.refresh_token)

    sessions.revoke_token.assert_awaited_once()
    with pytest.raises(InvalidRefreshTokenError) as raised:
        await service.refresh(session.refresh_token)
    # A closed session is not a reuse: the account's other devices stay open.
    assert not isinstance(raised.value, ReusedRefreshTokenError)


async def test_logging_out_revokes_the_family_including_its_rotated_tokens(service, tokens):
    first = await log_in(service)
    second = await service.refresh(first.refresh_token)

    await service.logout(second.access_token, second.refresh_token)

    assert all(row.revoked_at is not None for row in tokens.rows)


async def test_logging_out_leaves_the_other_devices_open(service):
    phone = await log_in(service)
    laptop = await log_in(service)

    await service.logout(phone.access_token, phone.refresh_token)

    assert (await service.refresh(laptop.refresh_token)).refresh_token


async def test_logging_out_without_a_refresh_token_still_works(service, tokens, sessions):
    session = await log_in(service)

    await service.logout(session.access_token)

    sessions.revoke_token.assert_awaited_once()
    assert all(row.revoked_at is None for row in tokens.rows)


async def test_logging_out_ignores_a_refresh_token_nobody_issued(service, tokens):
    session = await log_in(service)

    await service.logout(session.access_token, "not-a-token-that-was-ever-issued")

    assert all(row.revoked_at is None for row in tokens.rows)


async def test_logging_out_ignores_a_refresh_token_of_another_account(service, tokens, users):
    mine = await log_in(service)
    users.find_by_identifier.return_value = build_user(
        id=uuid.uuid4(), email="otra@udesa.edu.ar", handle="@otra_02"
    )
    theirs = await log_in(service, identifier="otra@udesa.edu.ar")

    await service.logout(mine.access_token, theirs.refresh_token)

    assert all(row.revoked_at is None for row in tokens.rows)
    assert (await service.refresh(theirs.refresh_token)).refresh_token


async def test_logging_out_with_an_expired_access_token_still_closes_the_family(
    service, tokens, sessions, signing_key, user
):
    session = await log_in(service)
    expired = issue_access_token(
        signing_key,
        subject=user.id,
        role="user",
        handle=user.handle,
        profile_visibility="public",
        expires_in_minutes=15,
        issuer=service.settings.jwt_issuer,
        now=datetime.now(UTC) - timedelta(hours=1),
    )

    await service.logout(expired, session.refresh_token)

    # Nothing to revoke on the access token side, and still a 204 for the app.
    sessions.revoke_token.assert_not_awaited()
    with pytest.raises(InvalidRefreshTokenError):
        await service.refresh(session.refresh_token)


async def test_logging_out_with_a_bad_access_token_leaves_the_refresh_token_alone(service, tokens):
    session = await log_in(service)

    with pytest.raises(ProblemError) as raised:
        await service.logout("not-a-jwt", session.refresh_token)

    assert raised.value.status == 401
    assert all(row.revoked_at is None for row in tokens.rows)
