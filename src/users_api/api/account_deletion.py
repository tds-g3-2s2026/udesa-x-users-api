"""Closing the account of whoever makes the call.

Under `/me`, next to `profile.py` and `password_change.py`: this is something
you do to the account you are already signed into. The password travels in the
body of the DELETE because the request has to prove who is holding the session,
not only that the session is valid.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from users_api.api.deps import (
    CurrentUserDep,
    OutboxRepositoryDep,
    RateLimiterDep,
    RefreshTokenRepositoryDep,
    SessionStoreDep,
    SettingsDep,
    UserRepositoryDep,
)
from users_api.api.schemas.account_deletion import DeleteAccountRequest
from users_api.app.services.account_deletion import AccountDeletionService

router = APIRouter(prefix="/me", tags=["auth"])


async def get_account_deletion_service(
    users: UserRepositoryDep,
    refresh_tokens: RefreshTokenRepositoryDep,
    rate_limiter: RateLimiterDep,
    sessions: SessionStoreDep,
    settings: SettingsDep,
    outbox: OutboxRepositoryDep,
) -> AccountDeletionService:
    return AccountDeletionService(
        users=users,
        refresh_tokens=refresh_tokens,
        rate_limiter=rate_limiter,
        sessions=sessions,
        settings=settings,
        outbox=outbox,
    )


ServiceDep = Annotated[AccountDeletionService, Depends(get_account_deletion_service)]


@router.delete("")
async def delete_account(
    payload: DeleteAccountRequest, user: CurrentUserDep, service: ServiceDep
) -> dict[str, str]:
    """Close the account of the caller.

    Answering 200 means the account is closed and every session of it is gone,
    the one that made this call included: the app has to send the user back to
    the login screen without calling logout first.
    """
    await service.delete_account(user, current_password=payload.current_password)
    return {"status": "deleted"}
