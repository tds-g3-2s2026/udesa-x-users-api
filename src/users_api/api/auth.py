from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from users_api.api.deps import (
    EmailSenderDep,
    RateLimiterDep,
    SessionStoreDep,
    SettingsDep,
    SigningKeyDep,
    UserRepositoryDep,
    VerificationTokenRepositoryDep,
)
from users_api.api.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    VerifyRequest,
)
from users_api.app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


async def get_auth_service(
    users: UserRepositoryDep,
    verification_tokens: VerificationTokenRepositoryDep,
    rate_limiter: RateLimiterDep,
    sessions: SessionStoreDep,
    settings: SettingsDep,
    signing_key: SigningKeyDep,
    email_sender: EmailSenderDep,
) -> AuthService:
    return AuthService(
        users=users,
        verification_tokens=verification_tokens,
        rate_limiter=rate_limiter,
        sessions=sessions,
        settings=settings,
        signing_key=signing_key,
        email_sender=email_sender,
    )


ServiceDep = Annotated[AuthService, Depends(get_auth_service)]

# Rejects a missing or malformed Authorization header before the service ever
# sees the request, with the standard 401/403.
bearer_scheme = HTTPBearer()
BearerDep = Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)]


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, service: ServiceDep) -> RegisterResponse:
    """Create the account and send the verification link.

    The account starts unverified: it stays out of the system until the emailed
    token is consumed.
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
    """Ask for a new verification link.

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
    """Revoke the caller's token."""
    await service.logout(credentials.credentials)
