"""Administrator accounts, managed from the panel.

Apart from `/admin/auth`: that one is the door, this one is what a superadmin
does once inside. Every route here is refused to a moderator.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status

from users_api.api.deps import SettingsDep, SuperadminDep, UserRepositoryDep
from users_api.api.schemas.admin_users import (
    AdministratorCredentialResponse,
    AdministratorResponse,
    CreateAdministratorRequest,
)
from users_api.app.models.user import Role, User
from users_api.app.services.admins import AdminService

router = APIRouter(prefix="/admin/users", tags=["admin"])


async def get_admin_service(users: UserRepositoryDep, settings: SettingsDep) -> AdminService:
    return AdminService(users=users, settings=settings)


ServiceDep = Annotated[AdminService, Depends(get_admin_service)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_administrator(
    payload: CreateAdministratorRequest,
    _: SuperadminDep,
    service: ServiceDep,
) -> AdministratorCredentialResponse:
    """Create an administrator and answer with its temporary password.

    The password comes back once and is never retrievable again: the account
    stores a hash of it, like every other account does.
    """
    user, temporary_password = await service.create_administrator(
        email=payload.email,
        handle=payload.handle,
        role=Role(payload.role),
    )
    return credential(user, temporary_password)


@router.post("/{user_id}/reset-temporary-password")
async def reset_temporary_password(
    user_id: uuid.UUID,
    _: SuperadminDep,
    service: ServiceDep,
) -> AdministratorCredentialResponse:
    """Replace the temporary password of an administrator that never used it.

    Answers the same shape as the creation, for the same reason: this is the
    one moment the new password can be read.
    """
    user, temporary_password = await service.reset_temporary_password(user_id)
    return credential(user, temporary_password)


@router.get("")
async def list_administrators(_: SuperadminDep, service: ServiceDep) -> list[AdministratorResponse]:
    """Every administrator, with the state of its temporary credential."""
    now = datetime.now(UTC)
    return [
        AdministratorResponse(
            id=str(user.id),
            email=user.email,
            handle=user.handle,
            role=user.role.value,
            temporary_password_status=temporary_password_status(user, now),
            temporary_password_expires_at=user.temporary_password_expires_at,
        )
        for user in await service.list_administrators()
    ]


def temporary_password_status(user: User, now: datetime) -> str | None:
    """What the panel shows next to the account, in one word."""
    if not user.must_change_password:
        return None
    return "expired" if user.temporary_password_expired(now) else "pending"


def credential(user: User, temporary_password: str) -> AdministratorCredentialResponse:
    return AdministratorCredentialResponse(
        id=str(user.id),
        email=user.email,
        handle=user.handle,
        role=user.role.value,
        temporary_password=temporary_password,
    )
