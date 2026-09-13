"""Reading and editing the preferences of the account making the call.

Under `/me`, next to `profile.py`: a separate resource and not two more fields
on the profile response, because the two things are edited from different
screens and answer different questions — who this account shows itself as,
versus how it wants the app to behave for it.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from users_api.api.deps import CurrentUserDep, UserRepositoryDep
from users_api.api.schemas.preferences import PreferencesResponse, UpdatePreferencesRequest
from users_api.app.services.preferences import PreferencesService

router = APIRouter(prefix="/me/preferences", tags=["preferences"])


async def get_preferences_service(users: UserRepositoryDep) -> PreferencesService:
    return PreferencesService(users=users)


ServiceDep = Annotated[PreferencesService, Depends(get_preferences_service)]


def to_response(user) -> PreferencesResponse:
    return PreferencesResponse(
        profile_visibility=user.profile_visibility,
        feed_language=user.feed_language,
    )


@router.get("")
async def get_preferences(user: CurrentUserDep) -> PreferencesResponse:
    return to_response(user)


@router.patch("")
async def update_preferences(
    payload: UpdatePreferencesRequest, user: CurrentUserDep, service: ServiceDep
) -> PreferencesResponse:
    changes = payload.model_dump(exclude_unset=True)
    updated = await service.update_preferences(user, changes=changes)
    return to_response(updated)
