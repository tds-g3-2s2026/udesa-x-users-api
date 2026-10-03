from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from users_api.api.deps import (
    EmailSenderDep,
    RateLimiterDep,
    RefreshTokenRepositoryDep,
    SessionStoreDep,
    SettingsDep,
    SigningKeyDep,
    UserRepositoryDep,
    VerificationTokenRepositoryDep,
)
from users_api.api.errors import problem_error_handler
from users_api.api.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    VerifyRequest,
)
from users_api.app.services.auth import AuthService, ReusedRefreshTokenError

router = APIRouter(prefix="/auth", tags=["auth"])


async def get_auth_service(
    users: UserRepositoryDep,
    verification_tokens: VerificationTokenRepositoryDep,
    refresh_tokens: RefreshTokenRepositoryDep,
    rate_limiter: RateLimiterDep,
    sessions: SessionStoreDep,
    settings: SettingsDep,
    signing_key: SigningKeyDep,
    email_sender: EmailSenderDep,
) -> AuthService:
    return AuthService(
        users=users,
        verification_tokens=verification_tokens,
        refresh_tokens=refresh_tokens,
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


@router.get("/verify")
async def verify_from_link(token: str, service: ServiceDep) -> dict[str, str]:
    """The emailed link: a mail client can only open it with a GET."""
    user = await service.verify_email(token)
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
    session = await service.login(
        identifier=payload.identifier,
        password=payload.password,
    )
    return LoginResponse(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_in=session.expires_in,
    )


@router.post("/refresh", response_model=LoginResponse)
async def refresh(
    payload: RefreshRequest, request: Request, service: ServiceDep
) -> LoginResponse | JSONResponse:
    """Trade a refresh token for a new access token and the next refresh token.

    Each refresh token works once. Presenting one a second time signs the whole
    account out, and the answer is the same 401 as for any other invalid token.
    """
    try:
        session = await service.refresh(payload.refresh_token)
    except ReusedRefreshTokenError as reused:
        # Answered and not raised: raising rolls the transaction back, and with
        # it the revocation of the account's refresh tokens that the service
        # just wrote.
        return await problem_error_handler(request, reused)
    return LoginResponse(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_in=session.expires_in,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    credentials: BearerDep, service: ServiceDep, payload: LogoutRequest | None = None
) -> None:
    """Revoke the caller's token, and the family of the refresh token if one comes along."""
    await service.logout(credentials.credentials, payload.refresh_token if payload else None)
