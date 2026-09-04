"""How the business reaches the emailed tokens it handed out."""

import uuid
from abc import ABC, abstractmethod
from datetime import datetime

from users_api.app.models.tokens import EmailVerificationToken, PasswordResetToken


class EmailVerificationTokenRepository(ABC):
    @abstractmethod
    async def add(self, token: EmailVerificationToken) -> None: ...

    @abstractmethod
    async def find_by_hash(self, token_hash: str) -> EmailVerificationToken | None: ...

    @abstractmethod
    async def mark_used(self, token_id: uuid.UUID, *, used_at: datetime) -> None: ...


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
