"""Changing the password from inside the session.

Under `/me` and not under `/auth`: the rest of `/auth` is what you call to get a
session, and this is something you do to the account you are already signed into.
The forced change on an administrator's first login reuses it.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from users_api.api.deps import (
    CurrentUserDep,
    EmailSenderDep,
    RateLimiterDep,
    SessionStoreDep,
    SettingsDep,
    UserRepositoryDep,
)
from users_api.api.schemas.password_change import ChangePasswordRequest
from users_api.app.services.password_change import PasswordChangeService

router = APIRouter(prefix="/me", tags=["auth"])


async def get_password_change_service(
    users: UserRepositoryDep,
    rate_limiter: RateLimiterDep,
    sessions: SessionStoreDep,
    settings: SettingsDep,
    email_sender: EmailSenderDep,
) -> PasswordChangeService:
    return PasswordChangeService(
        users=users,
        rate_limiter=rate_limiter,
        sessions=sessions,
        settings=settings,
        email_sender=email_sender,
    )


ServiceDep = Annotated[PasswordChangeService, Depends(get_password_change_service)]


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest, user: CurrentUserDep, service: ServiceDep
) -> dict[str, str]:
    """Change the password of the account making the call.

    Answering 200 means every session of this account is gone, the one that made
    this call included: the app has to send the user back to the login screen.
    """
    await service.change_password(
        user,
        current_password=payload.current_password,
        new_password=payload.password,
    )
    return {"status": "changed"}
