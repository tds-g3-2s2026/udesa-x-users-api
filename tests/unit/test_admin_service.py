"""AdminService against a repository double."""

import uuid
from unittest.mock import AsyncMock

import pytest

from users_api.app.errors import ProblemError
from users_api.app.models.user import Role, User
from users_api.app.repositories.users import UserRepository
from users_api.app.security import verify_password
from users_api.app.services.admins import AdminService

PASSWORD = "Admin1234"


@pytest.fixture
def users():
    repository = AsyncMock(spec=UserRepository)
    repository.find_by_email.return_value = None
    repository.exists_with_email_or_handle.return_value = False
    repository.add.side_effect = lambda user: user
    return repository


async def test_e5_h2_the_seeded_superadmin_is_verified_and_carries_the_role(users):
    created = await AdminService(users=users).ensure_superadmin(
        email="Admin@udesa.edu.ar", handle="@SuperAdmin", password=PASSWORD
    )

    assert created is not None
    assert created.role is Role.SUPERADMIN
    assert created.is_email_verified is True
    assert created.terms_accepted is True
    # Normalised like registration, so uniqueness stays case-insensitive.
    assert (created.email, created.handle) == ("admin@udesa.edu.ar", "@superadmin")
    assert verify_password(PASSWORD, created.password_hash)


async def test_e5_h2_the_seed_leaves_an_existing_account_alone(users):
    users.find_by_email.return_value = User(
        id=uuid.uuid4(), email="admin@udesa.edu.ar", handle="@alumno", password_hash="x"
    )

    created = await AdminService(users=users).ensure_superadmin(
        email="admin@udesa.edu.ar", handle="@superadmin", password=PASSWORD
    )

    assert created is None
    users.add.assert_not_awaited()
    users.update.assert_not_awaited()


async def test_e5_h1_the_new_administrator_is_born_owing_a_password_change(users):
    created, temporary_password = await AdminService(users=users).create_administrator(
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


async def test_e5_h1_each_administrator_gets_a_different_temporary_password(users):
    service = AdminService(users=users)

    _, first = await service.create_administrator(
        email="una@udesa.edu.ar", handle="@una_admin", role=Role.MODERATOR
    )
    _, second = await service.create_administrator(
        email="otra@udesa.edu.ar", handle="@otra_admin", role=Role.MODERATOR
    )

    assert first != second


async def test_e5_h1_an_address_already_in_use_is_refused(users):
    users.exists_with_email_or_handle.return_value = True

    with pytest.raises(ProblemError) as raised:
        await AdminService(users=users).create_administrator(
            email="admin@udesa.edu.ar", handle="@otro_admin", role=Role.SUPERADMIN
        )

    assert raised.value.status == 409
    users.add.assert_not_awaited()
