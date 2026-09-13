"""Editing the preferences of the account making the call."""

from dataclasses import dataclass

from users_api.app.models.user import User
from users_api.app.repositories.users import UserRepository


@dataclass
class PreferencesService:
    users: UserRepository

    async def update_preferences(self, user: User, *, changes: dict) -> User:
        """Apply only the fields the caller actually sent.

        `changes` comes from the request with the unset fields already
        dropped, so a key present here is a field the schema already
        validated against the enum: this only decides which attributes to
        touch, the same split `ProfileService` uses.
        """
        if "profile_visibility" in changes:
            user.profile_visibility = changes["profile_visibility"]
        if "feed_language" in changes:
            user.feed_language = changes["feed_language"]
        await self.users.update(user)
        return user
