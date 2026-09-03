"""How password recovery reaches its stored links.

Accounts are read through `UserRepository`, which belongs to authentication:
recovery reads and updates the same account, and duplicating the interface would
mean two ways of asking the same question.
"""

import uuid
from abc import ABC, abstractmethod
from datetime import datetime

from users_api.features.password_reset.domain import PasswordResetToken


class PasswordResetTokenRepository(ABC):
    @abstractmethod
    async def add(self, token: PasswordResetToken) -> None: ...

    @abstractmethod
    async def find_by_hash(self, token_hash: str) -> PasswordResetToken | None: ...

    @abstractmethod
    async def mark_all_used(self, user_id: uuid.UUID, *, used_at: datetime) -> None:
        """Close every open link of the account at once.

        Consuming one link kills the rest: one sent minutes earlier would still
        be a way in after the password already changed.
        """
