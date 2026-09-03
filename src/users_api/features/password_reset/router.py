from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from users_api.core.deps import get_session
from users_api.features.password_reset.schemas import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from users_api.features.password_reset.service import PasswordResetService

router = APIRouter(prefix="/auth", tags=["auth"])


async def get_reset_service(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> PasswordResetService:
    state = request.app.state
    return PasswordResetService(
        session=session,
        redis=state.redis,
        settings=state.settings,
        email_sender=state.email_sender,
    )


ServiceDep = Annotated[PasswordResetService, Depends(get_reset_service)]


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(payload: ForgotPasswordRequest, service: ServiceDep) -> dict[str, str]:
    """Ask for a reset link with the email or the handle.

    The answer is always this one, registered or not, so the endpoint never
    tells an attacker which accounts exist.
    """
    await service.forgot_password(payload.identifier)
    return {"status": "accepted"}


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordRequest, service: ServiceDep) -> dict[str, str]:
    """Consume the link and set the new password.

    No Authorization header: whoever gets here is precisely the person who
    cannot log in. What proves ownership is the token that arrived by email.
    """
    user = await service.reset_password(payload.token, payload.password)
    return {"status": "reset", "handle": user.handle}
