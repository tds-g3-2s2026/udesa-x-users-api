"""Editing the profile of the account making the call."""

from dataclasses import dataclass

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
