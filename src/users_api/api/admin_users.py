"""Administrator accounts, managed from the panel.

Apart from `/admin/auth`: that one is the door, this one is what a superadmin
does once inside. Every route here is refused to a moderator.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from users_api.api.deps import SuperadminDep, UserRepositoryDep
from users_api.api.schemas.admin_users import (
    CreateAdministratorRequest,
    CreatedAdministratorResponse,
)
from users_api.app.models.user import Role
from users_api.app.services.admins import AdminService

router = APIRouter(prefix="/admin/users", tags=["admin"])


async def get_admin_service(users: UserRepositoryDep) -> AdminService:
    return AdminService(users=users)


ServiceDep = Annotated[AdminService, Depends(get_admin_service)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_administrator(
    payload: CreateAdministratorRequest,
    _: SuperadminDep,
    service: ServiceDep,
) -> CreatedAdministratorResponse:
    """Create an administrator and answer with its temporary password.

    The password comes back once and is never retrievable again: the account
    stores a hash of it, like every other account does.
    """
    user, temporary_password = await service.create_administrator(
        email=payload.email,
        handle=payload.handle,
        role=Role(payload.role),
    )
    return CreatedAdministratorResponse(
        id=str(user.id),
        email=user.email,
        handle=user.handle,
        role=user.role.value,
        temporary_password=temporary_password,
    )
