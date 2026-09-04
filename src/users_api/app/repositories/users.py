"""How the business reaches stored accounts, without naming a database.

The services depend on this interface and never on the engine underneath. That
is what lets the same service run against PostgreSQL today and against something
else later, and what lets the unit tests replace it with a double.
"""

import uuid
from abc import ABC, abstractmethod

from users_api.app.models.user import User


class UserRepository(ABC):
    @abstractmethod
    async def add(self, user: User) -> User:
        """Store a new account and return it with its assigned id."""

    @abstractmethod
    async def get(self, user_id: uuid.UUID) -> User | None: ...

    @abstractmethod
    async def find_by_identifier(self, identifier: str) -> User | None:
        """Look an account up by email or by handle, indistinctly.

        Login accepts either one, and which of the two arrived is not something
        the caller has to resolve beforehand.
        """

    @abstractmethod
    async def find_by_email(self, email: str) -> User | None: ...

    @abstractmethod
    async def exists_with_email_or_handle(self, email: str, handle: str) -> bool: ...

    @abstractmethod
    async def update(self, user: User) -> None:
        """Persist the changes made to an account already stored."""
