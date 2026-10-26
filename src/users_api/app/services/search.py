"""Public account search filtered by the service owning blocks."""

from uuid import UUID

from users_api.app.clients.blocks import BlocksClient, BlocksUnavailableError
from users_api.app.errors import ProblemError
from users_api.app.models.search import SEARCH_BATCH_SIZE, SearchCandidate
from users_api.app.repositories.users import UserRepository


class UserSearchService:
    def __init__(self, users: UserRepository, blocks: BlocksClient) -> None:
        self._users = users
        self._blocks = blocks

    async def search(
        self, query: str, viewer_id: UUID, cursor: str | None
    ) -> tuple[list[SearchCandidate], str | None]:
        fragment = query.strip()
        handle_only = fragment.startswith("@")
        if handle_only:
            fragment = fragment[1:]
        if len(fragment) < 3:
            raise ProblemError(
                status=422,
                code="invalid-query",
                title="Búsqueda inválida",
                detail="Escribí al menos 3 caracteres sin contar el @ inicial",
            )
        visible: list[SearchCandidate] = []
        while len(visible) < 21:
            candidates = await self._users.search_public_accounts(
                fragment, handle_only=handle_only, cursor=cursor
            )
            if not candidates:
                break
            try:
                excluded = await self._blocks.excluded_ids(
                    viewer_id, [row.user.id for row in candidates]
                )
            except BlocksUnavailableError as error:
                raise ProblemError(
                    status=503,
                    code="search-unavailable",
                    title="Búsqueda no disponible",
                    detail="No se pudieron comprobar los bloqueos. Intentalo de nuevo.",
                ) from error
            visible.extend(row for row in candidates if row.user.id not in excluded)
            if len(candidates) < SEARCH_BATCH_SIZE:
                break
            cursor = candidates[-1].cursor
        return visible[:20], visible[19].cursor if len(visible) > 20 else None
