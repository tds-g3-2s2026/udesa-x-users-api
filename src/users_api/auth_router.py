from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from users_api.auth_service import AuthService
from users_api.db import session_scope
from users_api.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    ResetPasswordRequest,
    VerifyRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])


async def get_auth_service(request: Request) -> AuthService:
    """Build the service with the connections opened once in the lifespan."""
    state = request.app.state
    async for session in session_scope(state.session_factory):
        yield AuthService(
            session=session,
            redis=state.redis,
            settings=state.settings,
            signing_key=state.signing_key,
            email_sender=state.email_sender,
        )


ServiceDep = Annotated[AuthService, Depends(get_auth_service)]

# Rejects a missing or malformed Authorization header before the service ever
# sees the request, with the standard 401/403.
bearer_scheme = HTTPBearer()
BearerDep = Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)]


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, service: ServiceDep) -> RegisterResponse:
    """Create the account and send the verification link.

    The account starts unverified: E1-H1 CA.1 keeps it out of the system until
    the emailed token is consumed.
    """
    user = await service.register(
        email=payload.email,
        handle=payload.handle,
        password=payload.password,
    )
    return RegisterResponse(id=str(user.id), email=user.email, handle=user.handle)


@router.post("/verify")
async def verify(payload: VerifyRequest, service: ServiceDep) -> dict[str, str]:
    user = await service.verify_email(payload.token)
    return {"status": "verified", "handle": user.handle}


@router.post("/resend-verification", status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(
    payload: ResendVerificationRequest, service: ServiceDep
) -> dict[str, str]:
    """Ask for a new verification link, as E1-H1 CA.6 requires.

    The answer is always the same whether or not the address is registered.
    """
    await service.resend_verification(payload.email)
    return {"status": "accepted"}


@router.post("/login")
async def login(payload: LoginRequest, service: ServiceDep) -> LoginResponse:
    token, expires_in = await service.login(
        identifier=payload.identifier,
        password=payload.password,
    )
    return LoginResponse(access_token=token, expires_in=expires_in)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(credentials: BearerDep, service: ServiceDep) -> None:
    """Revoke the caller's token, E1-H3 CA.1."""
    await service.logout(credentials.credentials)


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(payload: ForgotPasswordRequest, service: ServiceDep) -> dict[str, str]:
    """Ask for a reset link with the email or the handle, E1-H5.

    The answer is always this one, registered or not: E1-H5 CA.4 keeps the
    endpoint from telling an attacker which accounts exist.
    """
    await service.forgot_password(payload.identifier)
    return {"status": "accepted"}


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordRequest, service: ServiceDep) -> dict[str, str]:
    """Consume the link and set the new password, E1-H5.

    No Authorization header: whoever gets here is precisely the person who
    cannot log in. What proves ownership is the token that arrived by email.
    """
    user = await service.reset_password(payload.token, payload.password)
    return {"status": "reset", "handle": user.handle}
