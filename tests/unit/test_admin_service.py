"""AdminService and the rules around a temporary password."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from users_api.app.errors import ProblemError
from users_api.app.models.user import Role, User
from users_api.app.repositories.users import UserRepository
from users_api.app.security import verify_password
from users_api.app.services.admins import TEMPORARY_PASSWORD_HOURS, AdminService
from users_api.config.settings import Settings

PASSWORD = "Admin1234"


def build_settings(**overrides) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://unused",
        redis_url="redis://unused",
        **overrides,
    )


@pytest.fixture
def users():
    repository = AsyncMock(spec=UserRepository)
    repository.find_by_email.return_value = None
    repository.exists_with_email_or_handle.return_value = False
    repository.add.side_effect = lambda user: user
    return repository


@pytest.fixture
def service(users):
    return AdminService(users=users, settings=build_settings())


async def test_e5_h2_the_seeded_superadmin_is_verified_and_carries_the_role(service):
    created = await service.ensure_superadmin(
        email="Admin@udesa.edu.ar", handle="@SuperAdmin", password=PASSWORD
    )

    assert created is not None
    assert created.role is Role.SUPERADMIN
    assert created.is_email_verified is True
    assert created.terms_accepted is True
    # Normalised like registration, so uniqueness stays case-insensitive.
    assert (created.email, created.handle) == ("admin@udesa.edu.ar", "@superadmin")
    assert verify_password(PASSWORD, created.password_hash)


async def test_e5_h2_the_seed_leaves_an_existing_account_alone(users, service):
    users.find_by_email.return_value = User(
        id=uuid.uuid4(), email="admin@udesa.edu.ar", handle="@alumno", password_hash="x"
    )

    created = await service.ensure_superadmin(
        email="admin@udesa.edu.ar", handle="@superadmin", password=PASSWORD
    )

    assert created is None
    users.add.assert_not_awaited()
    users.update.assert_not_awaited()


async def test_e5_h1_the_new_administrator_is_born_owing_a_password_change(service):
    created, temporary_password = await service.create_administrator(
        email="Nueva@udesa.edu.ar", handle="@Moderadora", role=Role.MODERATOR
    )

    assert created.must_change_password is True
    assert created.role is Role.MODERATOR
    # Nobody is going to click a verification link for an account somebody
    # else created.
    assert created.is_email_verified is True
    assert (created.email, created.handle) == ("nueva@udesa.edu.ar", "@moderadora")
    # What comes back is the only copy in clear; what is stored is a hash.
    assert verify_password(temporary_password, created.password_hash)
    assert temporary_password not in created.password_hash


async def test_e5_h1_each_administrator_gets_a_different_temporary_password(service):

    _, first = await service.create_administrator(
        email="una@udesa.edu.ar", handle="@una_admin", role=Role.MODERATOR
    )
    _, second = await service.create_administrator(
        email="otra@udesa.edu.ar", handle="@otra_admin", role=Role.MODERATOR
    )

    assert first != second


async def test_e5_h1_an_address_already_in_use_is_refused(users, service):
    users.exists_with_email_or_handle.return_value = True

    with pytest.raises(ProblemError) as raised:
        await service.create_administrator(
            email="admin@udesa.edu.ar", handle="@otro_admin", role=Role.SUPERADMIN
        )

    assert raised.value.status == 409
    users.add.assert_not_awaited()


async def test_e5_h1_the_temporary_password_is_given_a_day_to_be_used(service):
    before = datetime.now(UTC)

    created, _ = await service.create_administrator(
        email="nueva@udesa.edu.ar", handle="@nueva_admin", role=Role.MODERATOR
    )

    expected = before + timedelta(hours=TEMPORARY_PASSWORD_HOURS)
    assert created.temporary_password_expires_at >= expected
    assert created.temporary_password_expires_at < expected + timedelta(minutes=1)


def test_e5_h1_the_temporary_password_stops_working_once_its_moment_passes():
    expires_at = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    account = User(
        email="nueva@udesa.edu.ar",
        handle="@nueva_admin",
        password_hash="x",
        must_change_password=True,
        temporary_password_expires_at=expires_at,
    )

    assert account.temporary_password_expired(expires_at - timedelta(seconds=1)) is False
    # The deadline itself is already too late.
    assert account.temporary_password_expired(expires_at) is True


def test_e5_h1_a_password_its_owner_chose_never_expires():
    account = User(
        email="alumno@udesa.edu.ar",
        handle="@alumno_01",
        password_hash="x",
        must_change_password=False,
        temporary_password_expires_at=datetime(2020, 1, 1, tzinfo=UTC),
    )

    assert account.temporary_password_expired(datetime.now(UTC)) is False


async def test_e5_h1_ca4_an_address_outside_the_configured_domain_is_refused(users):
    service = AdminService(
        users=users, settings=build_settings(administrator_email_domain="udesa.edu.ar")
    )

    with pytest.raises(ProblemError) as raised:
        await service.create_administrator(
            email="externo@gmail.com", handle="@externo_01", role=Role.MODERATOR
        )

    assert raised.value.status == 400
    users.add.assert_not_awaited()


async def test_e5_h1_ca4_without_a_configured_domain_any_address_goes(service):
    created, _ = await service.create_administrator(
        email="externo@gmail.com", handle="@externo_01", role=Role.MODERATOR
    )

    assert created.email == "externo@gmail.com"
