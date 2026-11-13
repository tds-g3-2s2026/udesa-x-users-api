"""App accounts as the backoffice reaches them: found and read (E5-H4), blocked (E5-H5),
exported (E5-H8) and their biography cleared (E5-H10).

Same `/admin/users` prefix as `admin_users.py`, but a router of its own: that one
manages administrators and refuses moderators, and this one is open to any
administrator except for the export. `/search` and `/export.csv` are declared
before `/{user_id}`, so neither is read as an id.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse

from users_api.api.accounts_csv import csv_lines
from users_api.api.deps import (
    AdministratorDep,
    AuditLogDep,
    RefreshTokenRepositoryDep,
    SessionStoreDep,
    SettingsDep,
    SuperadminDep,
    UserRepositoryDep,
)
from users_api.api.schemas.admin_users import (
    BlockAccountRequest,
    UserAccountPage,
    UserAccountResponse,
)
from users_api.app.models.user import User
from users_api.app.services.account_block import AccountBlockService
from users_api.app.services.account_content import AccountContentService
from users_api.app.services.admin_user_accounts import AdminUserAccountService

router = APIRouter(prefix="/admin/users", tags=["admin"])


async def get_account_service(users: UserRepositoryDep) -> AdminUserAccountService:
    return AdminUserAccountService(users=users)


ServiceDep = Annotated[AdminUserAccountService, Depends(get_account_service)]


async def get_block_service(
    users: UserRepositoryDep,
    sessions: SessionStoreDep,
    refresh_tokens: RefreshTokenRepositoryDep,
    settings: SettingsDep,
    audit: AuditLogDep,
) -> AccountBlockService:
    return AccountBlockService(
        users=users,
        sessions=sessions,
        refresh_tokens=refresh_tokens,
        audit=audit,
        settings=settings,
    )


BlockServiceDep = Annotated[AccountBlockService, Depends(get_block_service)]


async def get_content_service(
    users: UserRepositoryDep, audit: AuditLogDep
) -> AccountContentService:
    return AccountContentService(users=users, audit=audit)


ContentServiceDep = Annotated[AccountContentService, Depends(get_content_service)]


def to_response(user: User) -> UserAccountResponse:
    return UserAccountResponse(
        id=str(user.id),
        email=user.email,
        handle=user.handle,
        display_name=user.display_name,
        bio=user.bio,
        status=user.status.value,
        status_reason=user.status_reason,
        status_changed_at=user.status_changed_at,
        is_email_verified=user.is_email_verified,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
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


@router.get("/export.csv")
async def export_accounts(
    _: SuperadminDep,
    service: ServiceDep,
    q: Annotated[str, Query(max_length=100)],
) -> StreamingResponse:
    """Every account the search finds for `q`, as a CSV download. Superadmin only (E5-H8)."""
    return StreamingResponse(
        csv_lines(service.export(q)),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="cuentas.csv"'},
    )


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


@router.post("/{user_id}/clean-content", status_code=status.HTTP_204_NO_CONTENT)
async def clean_account_content(
    user_id: uuid.UUID, administrator: AdministratorDep, service: ContentServiceDep
) -> None:
    """Replace the biography with the moderation placeholder (E5-H10). Any administrator."""
    await service.clean(administrator, user_id)
