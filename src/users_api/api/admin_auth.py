"""The backoffice login, apart from `/auth/login`.

Two doors and not one with a flag: the policies differ (three attempts and
thirty minutes here, five and fifteen in the app) and the 403 for a regular
user only makes sense on this side.
"""

from fastapi import APIRouter

from users_api.api.auth import ServiceDep
from users_api.api.schemas.auth import AdminLoginRequest, LoginResponse

router = APIRouter(prefix="/admin/auth", tags=["admin"])


@router.post("/login")
async def admin_login(payload: AdminLoginRequest, service: ServiceDep) -> LoginResponse:
    token, expires_in = await service.admin_login(email=payload.email, password=payload.password)
    return LoginResponse(access_token=token, expires_in=expires_in)
