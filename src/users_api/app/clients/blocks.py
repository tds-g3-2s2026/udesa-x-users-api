"""Read-only access to exclusions owned by the social graph."""

from abc import ABC, abstractmethod
from uuid import UUID


class BlocksUnavailableError(Exception):
    pass


class BlocksClient(ABC):
    @abstractmethod
    async def excluded_ids(self, viewer_id: UUID, user_ids: list[UUID]) -> set[UUID]: ...
