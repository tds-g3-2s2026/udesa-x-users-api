"""Reading and editing the profile of the account making the call.

Under `/me`, alongside `password_change.py`: this is something you do to the
account you are already signed into, not a way to get one.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from users_api.api.deps import CurrentUserDep, UserRepositoryDep
from users_api.api.schemas.profile import ProfileResponse, UpdateProfileRequest
from users_api.app.services.profile import ProfileService

router = APIRouter(prefix="/me", tags=["profile"])


async def get_profile_service(users: UserRepositoryDep) -> ProfileService:
    return ProfileService(users=users)


ServiceDep = Annotated[ProfileService, Depends(get_profile_service)]


def to_response(user) -> ProfileResponse:
    return ProfileResponse(
        id=str(user.id),
        email=user.email,
        handle=user.handle,
        display_name=user.display_name,
        bio=user.bio,
        onboarding_completed=user.onboarding_completed,
    )


@router.get("")
async def get_profile(user: CurrentUserDep) -> ProfileResponse:
    return to_response(user)


@router.patch("")
async def update_profile(
    payload: UpdateProfileRequest, user: CurrentUserDep, service: ServiceDep
) -> ProfileResponse:
    # Only the fields the caller actually sent, so omitting one leaves it as
    # it was instead of overwriting it with the default `None`.
    changes = payload.model_dump(exclude_unset=True)
    updated = await service.update_profile(user, changes=changes)
    return to_response(updated)


@router.post("/onboarding/complete", status_code=status.HTTP_204_NO_CONTENT)
async def complete_onboarding(user: CurrentUserDep, service: ServiceDep) -> Response:
    await service.complete_onboarding(user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
