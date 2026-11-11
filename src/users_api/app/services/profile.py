"""Editing the profile of the account making the call, and reading the public
part of anyone's."""

import uuid
from dataclasses import dataclass

from users_api.app.errors import ProblemError
from users_api.app.models.user import MIN_INTERESTS, User
from users_api.app.repositories.users import UserRepository


@dataclass
class ProfileService:
    users: UserRepository

    async def update_profile(self, user: User, *, changes: dict[str, str]) -> User:
        """Apply only the fields the caller actually sent.

        `changes` comes from the request with the unset fields already
        dropped, so a key present here is a field the schema already
        validated and sanitized: this only decides which attributes to touch.
        """
        if "display_name" in changes:
            user.display_name = changes["display_name"]
        if "bio" in changes:
            user.bio = changes["bio"]
        await self.users.update(user)
        return user

    async def complete_onboarding(self, user: User) -> None:
        """Mark the onboarding as done, once the account chose its interests.

        Asking again is not an error: the app may repeat the call after a lost
        answer. An account already done is left alone without looking at its
        interests, which is the case of every account that existed before the
        onboarding did.

        The account is read again under a lock, so the interests checked are
        the stored ones and not the ones the request loaded at its start.
        """
        user = await self.users.get_for_update(user.id) or user
        if user.onboarding_completed:
            return
        if len(user.interests) < MIN_INTERESTS:
            raise ProblemError(
                status=422,
                code="too-few-interests",
                title="Faltan intereses",
                detail=f"Elegí al menos {MIN_INTERESTS} intereses antes de terminar",
            )
        user.onboarding_completed = True
        await self.users.update(user)

    async def public_profile(self, user_id: uuid.UUID) -> User:
        """The account behind another user's profile screen (E2-H14).

        A deleted account answers the same 404 as one that never existed: its
        profile is gone for everyone, and the answer should not tell the two
        apart.
        """
        user = await self.users.get(user_id)
        if user is None or user.deleted_at is not None:
            raise ProblemError(
                status=404,
                code="account-not-found",
                title="No se encontró la cuenta",
                detail="La cuenta no existe",
            )
        return user
