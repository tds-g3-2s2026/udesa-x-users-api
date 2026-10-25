"""Routes that only the other services of the system call.

Under `/internal` and not under `/api`: the gateway only routes `/api`, so
nothing here is reachable from outside the cluster. Every route still asks for
the shared token, see `require_internal_token`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from users_api.api.deps import (
    AuditLogDep,
    RefreshTokenRepositoryDep,
    SessionStoreDep,
    SettingsDep,
    UserRepositoryDep,
    require_internal_token,
)
from users_api.api.schemas.audit import AdministratorIdentity
from users_api.api.schemas.profile import PublicProfileResponse
from users_api.app.services.account_review import AccountReviewService
from users_api.app.services.profile import ProfileService

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_token)],
)


async def get_account_review_service(
    users: UserRepositoryDep,
    refresh_tokens: RefreshTokenRepositoryDep,
    sessions: SessionStoreDep,
    settings: SettingsDep,
) -> AccountReviewService:
    return AccountReviewService(
        users=users, refresh_tokens=refresh_tokens, sessions=sessions, settings=settings
    )


ServiceDep = Annotated[AccountReviewService, Depends(get_account_review_service)]


async def get_profile_service(users: UserRepositoryDep) -> ProfileService:
    return ProfileService(users=users)


ProfileServiceDep = Annotated[ProfileService, Depends(get_profile_service)]


@router.post("/users/{user_id}/review", status_code=status.HTTP_204_NO_CONTENT)
async def put_under_review(user_id: uuid.UUID, service: ServiceDep) -> None:
    """Put the account under review and end every session it has open.

    posts-api calls this once an account is reported by more than five
    different users. Calling it again answers the same and changes nothing.
    """
    await service.put_under_review(user_id)


@router.delete("/users/{user_id}/review", status_code=status.HTTP_204_NO_CONTENT)
async def lift_review(user_id: uuid.UUID, service: ServiceDep) -> None:
    """Release the account from review, once the backoffice closed its case (E5-H7).

    posts-api calls this when an administrator dismisses or resolves the
    reports (ADR-020). An account not under review answers the same and does
    not change: a suspended one stays suspended.
    """
    await service.lift_review(user_id)


@router.get("/users/{user_id}/profile")
async def get_public_profile(
    user_id: uuid.UUID, service: ProfileServiceDep
) -> PublicProfileResponse:
    """The public part of an account, for another user's profile screen.

    posts-api calls this for E2-H14: the counters and the posts are its own,
    but the name, the biography and the registration date live here. The
    public response excludes the email.
    """
    user = await service.public_profile(user_id)
    return PublicProfileResponse(
        id=str(user.id),
        handle=user.handle,
        display_name=user.display_name,
        bio=user.bio,
        created_at=user.created_at,
    )


@router.get("/administrators/{actor_id}/identity")
async def administrator_identity(actor_id: uuid.UUID, audit: AuditLogDep) -> AdministratorIdentity:
    actor = await audit.administrator(actor_id)
    return AdministratorIdentity(id=actor.id, email=actor.email)
