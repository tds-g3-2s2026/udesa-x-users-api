"""Routes that only the other services of the system call.

Under `/internal` and not under `/api`: the gateway only routes `/api`, so
nothing here is reachable from outside the cluster. Every route still asks for
the shared token, see `require_internal_token`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from users_api.api.deps import (
    SessionStoreDep,
    SettingsDep,
    UserRepositoryDep,
    require_internal_token,
)
from users_api.app.services.account_review import AccountReviewService

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_token)],
)


async def get_account_review_service(
    users: UserRepositoryDep, sessions: SessionStoreDep, settings: SettingsDep
) -> AccountReviewService:
    return AccountReviewService(users=users, sessions=sessions, settings=settings)


ServiceDep = Annotated[AccountReviewService, Depends(get_account_review_service)]


@router.post("/users/{user_id}/review", status_code=status.HTTP_204_NO_CONTENT)
async def put_under_review(user_id: uuid.UUID, service: ServiceDep) -> None:
    """Put the account under review and end every session it has open.

    posts-api calls this once an account is reported by more than five
    different users. Calling it again answers the same and changes nothing.
    """
    await service.put_under_review(user_id)
