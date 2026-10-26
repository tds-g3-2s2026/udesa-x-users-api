"""App accounts as the backoffice reaches them: found and read (E5-H4), and blocked (E5-H5).

Same `/admin/users` prefix as `admin_users.py`, but a router of its own: that one
manages administrators and refuses moderators, and this one is open to any
administrator. `/search` is declared before `/{user_id}`, so "search" is never
read as an id.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from users_api.api.deps import (
    AdministratorDep,
    RefreshTokenRepositoryDep,
    SessionStoreDep,
    SettingsDep,
    UserRepositoryDep,
)
from users_api.api.schemas.admin_users import (
    BlockAccountRequest,
    UserAccountPage,
    UserAccountResponse,
)
from users_api.app.models.user import User
from users_api.app.services.account_block import AccountBlockService, InMemoryAuditLog
from users_api.app.services.admin_user_accounts import AdminUserAccountService

router = APIRouter(prefix="/admin/users", tags=["admin"])

# One for the whole process, so every request writes to the same place, until
# E5-H6 brings the audit table and its `AuditLog` takes this one's place.
audit_log = InMemoryAuditLog()


async def get_account_service(users: UserRepositoryDep) -> AdminUserAccountService:
    return AdminUserAccountService(users=users)


ServiceDep = Annotated[AdminUserAccountService, Depends(get_account_service)]


async def get_block_service(
    users: UserRepositoryDep,
    sessions: SessionStoreDep,
    refresh_tokens: RefreshTokenRepositoryDep,
    settings: SettingsDep,
) -> AccountBlockService:
    return AccountBlockService(
        users=users,
        sessions=sessions,
        refresh_tokens=refresh_tokens,
        audit=audit_log,
        settings=settings,
    )


BlockServiceDep = Annotated[AccountBlockService, Depends(get_block_service)]


def to_response(user: User) -> UserAccountResponse:
    return UserAccountResponse(
        id=str(user.id),
        email=user.email,
        handle=user.handle,
        display_name=user.display_name,
        status=user.status.value,
        status_reason=user.status_reason,
        status_changed_at=user.status_changed_at,
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
    """The account behind the detail screen: state, its reason and registration date."""
    return to_response(await service.account(user_id))


@router.post("/{user_id}/block", status_code=status.HTTP_204_NO_CONTENT)
async def block_account(
    user_id: uuid.UUID,
    body: BlockAccountRequest,
    administrator: AdministratorDep,
    service: BlockServiceDep,
) -> None:
    """Block the account with a reason and end every session it has open (E5-H5).

    Any administrator. Blocking an account already blocked answers the same and
    keeps the first reason.
    """
    await service.block(administrator, user_id, body.reason)
