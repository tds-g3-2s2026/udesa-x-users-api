"""Remembering which tokens stopped being valid before their own expiry."""

import uuid
from abc import ABC, abstractmethod
from datetime import datetime


class SessionStore(ABC):
    """Revocation of access tokens that were already handed out.

    A JWT is self-contained and was never stored, so a session is not closed by
    deleting a row: what gets recorded is that a token, or every token of an
    account, stopped being valid before its own expiry.

    Two mechanisms because they answer different questions. Revoking one token
    closes a session on one device. Revoking an account has to be recorded as a
    cutoff instant, because the jtis handed out were never kept and there is no
    list to walk: a token counts as revoked when it was issued before the cutoff.

    Writing is only half of it. Whoever authenticates a request has to ask back,
    or a revoked token would keep working until it expired on its own.
    """

    @abstractmethod
    async def revoke_token(self, jti: str, *, expires_at: datetime, now: datetime) -> None: ...

    @abstractmethod
    async def revoke_all(self, user_id: uuid.UUID, *, now: datetime, ttl_seconds: int) -> None: ...

    @abstractmethod
    async def is_token_revoked(self, jti: str) -> bool:
        """Whether this single token was revoked, by logging out."""

    @abstractmethod
    async def revoked_before(self, user_id: uuid.UUID) -> datetime | None:
        """The cutoff for this account, or None when it has none.

        A token of this account is revoked when it was issued before the instant
        this returns.
        """
