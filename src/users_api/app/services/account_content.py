"""An administrator clearing the biography of an app account (E5-H10).

The display name stays: the story names only the biography. posts-api keeps no
copy of the biography and asks for it each time a profile opens, so the
placeholder shows at once everywhere.
"""

import uuid
from dataclasses import dataclass

from users_api.app.errors import ProblemError
from users_api.app.models.user import User
from users_api.app.repositories.users import UserRepository
from users_api.app.services.audit import AuditLog

USER_CONTENT_CLEANED = "user.content_cleaned"
REMOVED_BY_MODERATION = "[Contenido eliminado por moderación]"


@dataclass
class AccountContentService:
    users: UserRepository
    audit: AuditLog

    async def clean(self, administrator: User, user_id: uuid.UUID) -> None:
        """Replace the biography with the placeholder.

        An empty biography stays empty and one already cleared is left alone,
        and neither leaves an entry in the audit. The account is read under a
        lock, so two administrators at once clear it and audit it only once.
        """
        user = await self.users.get_for_update(user_id)
        # The same accounts the detail screen shows: administrators are not app accounts.
        if user is None or user.deleted_at is not None or user.is_administrator:
            raise ProblemError(
                status=404,
                code="account-not-found",
                title="No se pudo limpiar el contenido",
                detail="La cuenta no existe",
            )
        if not user.bio or user.bio == REMOVED_BY_MODERATION:
            return

        user.bio = REMOVED_BY_MODERATION
        await self.users.update(user)
        await self.audit.record(
            administrator.id, USER_CONTENT_CLEANED, "user", user.id, {"fields": ["bio"]}
        )
