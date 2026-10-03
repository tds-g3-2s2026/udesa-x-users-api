"""How the business reaches the tokens it handed out."""

import uuid
from abc import ABC, abstractmethod
from datetime import datetime

from users_api.app.models.tokens import EmailVerificationToken, PasswordResetToken, RefreshToken


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


class RefreshTokenRepository(ABC):
    @abstractmethod
    async def add(self, token: RefreshToken) -> None: ...

    @abstractmethod
    async def find_by_hash(self, token_hash: str) -> RefreshToken | None: ...

    @abstractmethod
    async def consume(self, token_hash: str, *, now: datetime) -> RefreshToken | None:
        """Mark the token used and return it, or None when it cannot be used.

        One atomic step and not a read followed by a write: two requests
        presenting the same token at once must not both succeed, and a check
        done apart from the update would let them.

        Unknown, already used, revoked and expired tokens all come back as None.
        Telling them apart is `find_by_hash`'s job.
        """

    @abstractmethod
    async def revoke_family(self, family_id: uuid.UUID, *, revoked_at: datetime) -> None:
        """End one login's chain of tokens, the sessions of other devices stay."""

    @abstractmethod
    async def revoke_all(self, user_id: uuid.UUID, *, revoked_at: datetime) -> None:
        """End every chain of the account.

        What a password change or a reuse leaves behind: the cutoff written to
        the session store expires after the access token's life, and a refresh
        token that outlives it would then hand out working sessions again.
        """
