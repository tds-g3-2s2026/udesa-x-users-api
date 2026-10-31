"""Authenticated public account discovery."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from users_api.api.deps import CurrentUserDep, UserRepositoryDep, get_blocks_client
from users_api.app.clients.blocks import BlocksClient
from users_api.app.services.search import UserSearchService

router = APIRouter(prefix="/search", tags=["search"])


class SearchUserResponse(BaseModel):
    id: UUID
    handle: str
    display_name: str | None = Field(serialization_alias="displayName")
    is_private: bool = Field(serialization_alias="isPrivate")


class SearchUserPage(BaseModel):
    items: list[SearchUserResponse]
    next_cursor: str | None = Field(serialization_alias="nextCursor")


@router.get("/users")
async def search_users(
    q: Annotated[str, Query(min_length=3)],
    user: CurrentUserDep,
    users: UserRepositoryDep,
    blocks: Annotated[BlocksClient, Depends(get_blocks_client)],
    cursor: Annotated[str | None, Query()] = None,
) -> SearchUserPage:
    candidates, next_cursor = await UserSearchService(users, blocks).search(q, user.id, cursor)
    return SearchUserPage(
        items=[
            SearchUserResponse(
                id=row.user.id,
                handle=row.user.handle,
                display_name=row.user.display_name,
                is_private=row.user.profile_visibility.value == "protected",
            )
            for row in candidates
        ],
        next_cursor=next_cursor,
    )
