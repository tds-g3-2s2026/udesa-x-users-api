"""AdminService against a repository double."""

import uuid
from unittest.mock import AsyncMock

import pytest

from users_api.app.models.user import Role, User
from users_api.app.repositories.users import UserRepository
from users_api.app.security import verify_password
from users_api.app.services.admins import AdminService

PASSWORD = "Admin1234"


@pytest.fixture
def users():
    repository = AsyncMock(spec=UserRepository)
    repository.find_by_email.return_value = None
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
