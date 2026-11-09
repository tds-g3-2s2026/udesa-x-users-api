"""Looking app accounts up from the backoffice (E5-H4).

Apart from `admins.py`: that one manages administrator accounts and is for the
superadmin only. This one is how any administrator finds an app account to
give support or audit it.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from users_api.app.errors import ProblemError
from users_api.app.models.user import User
from users_api.app.repositories.users import UserRepository

PAGE_SIZE = 20
# Shorter than this matches most of the base, which is a listing and not a search.
MIN_QUERY_LENGTH = 3
# The export walks the same search in bigger pages: fewer round trips, and still
# never the whole result in memory.
EXPORT_PAGE_SIZE = 500


def searchable(query: str) -> str:
    """The text the search uses, refused when it is too short to be one."""
    fragment = query.strip()
    if len(fragment) < MIN_QUERY_LENGTH:
        raise ProblemError(
            status=422,
            code="search-query-too-short",
            title="No se pudo buscar",
            detail=f"La búsqueda necesita al menos {MIN_QUERY_LENGTH} caracteres",
        )
    return fragment


@dataclass
class AdminUserAccountService:
    users: UserRepository

    async def search(self, query: str, *, cursor: str | None) -> tuple[list[User], str | None]:
        """App accounts whose email or handle contain `query`, newest first."""
        return await self.users.search_user_accounts(
            searchable(query), cursor=cursor, limit=PAGE_SIZE
        )

    def export(self, query: str) -> AsyncIterator[User]:
        """Every account the search finds for `query`, in the same order (E5-H8).

        The text is checked here, before the response starts: once the file is
        on its way there is no status code left to refuse it with.
        """
        return self._every_match(searchable(query))

    async def _every_match(self, fragment: str) -> AsyncIterator[User]:
        cursor = None
        while True:
            users, cursor = await self.users.search_user_accounts(
                fragment, cursor=cursor, limit=EXPORT_PAGE_SIZE
            )
            for user in users:
                yield user
            if cursor is None:
                return

    async def account(self, user_id: uuid.UUID) -> User:
        """The app account behind the detail screen.

        Deleted accounts and administrators answer the same 404 as an unknown
        one: this screen is about app accounts, and administrators are managed
        apart.
        """
        user = await self.users.get(user_id)
        if user is None or user.deleted_at is not None or user.is_administrator:
            raise ProblemError(
                status=404,
                code="account-not-found",
                title="No se encontró la cuenta",
                detail="La cuenta no existe",
            )
        return user
