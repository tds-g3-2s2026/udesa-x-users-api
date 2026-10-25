"""App accounts as the backoffice reaches them (E5-H4).

Same `/admin/users` prefix as `admin_users.py`, but a router of its own: that one
manages administrators and refuses moderators, and this one is open to any
administrator. `/search` is declared before `/{user_id}`, so "search" is never
read as an id.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from users_api.api.deps import AdministratorDep, UserRepositoryDep
from users_api.api.schemas.admin_users import UserAccountPage, UserAccountResponse
from users_api.app.models.user import User
from users_api.app.services.admin_user_accounts import AdminUserAccountService

router = APIRouter(prefix="/admin/users", tags=["admin"])


async def get_account_service(users: UserRepositoryDep) -> AdminUserAccountService:
    return AdminUserAccountService(users=users)


ServiceDep = Annotated[AdminUserAccountService, Depends(get_account_service)]


def to_response(user: User) -> UserAccountResponse:
    return UserAccountResponse(
        id=str(user.id),
        email=user.email,
        handle=user.handle,
        display_name=user.display_name,
        status=user.status.value,
        is_email_verified=user.is_email_verified,
        created_at=user.created_at,
    )


@router.get("/search")
async def search_accounts(
    _: AdministratorDep,
    service: ServiceDep,
    q: Annotated[str, Query(max_length=100)],
    cursor: Annotated[str | None, Query()] = None,
) -> UserAccountPage:
    """App accounts whose email or handle contain `q`, twenty per page, newest first."""
    users, next_cursor = await service.search(q, cursor=cursor)
    return UserAccountPage(items=[to_response(one) for one in users], next_cursor=next_cursor)


@router.get("/{user_id}")
async def account_detail(
    user_id: uuid.UUID, _: AdministratorDep, service: ServiceDep
) -> UserAccountResponse:
    """The account behind the detail screen: state and registration date."""
    return to_response(await service.account(user_id))
