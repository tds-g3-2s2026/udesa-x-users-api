"""Editing the profile of the account making the call, and reading the public
part of anyone's."""

import uuid
from dataclasses import dataclass

from users_api.app.errors import ProblemError
from users_api.app.models.user import User
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
