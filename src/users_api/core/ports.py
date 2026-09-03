"""Interfaces the business logic depends on, with no technology behind them.

Everything in here is an abstract class the services talk to. The concrete
implementations live under `infrastructure/`, so replacing Redis, the mail
provider or the database means writing another class and wiring it in `deps.py`,
without opening a single service.

These three are cross-feature: both authentication and password recovery need to
count attempts, revoke sessions and send mail. The interfaces that belong to one
feature only live next to that feature, in its `repositories.py`.
"""

import uuid
from abc import ABC, abstractmethod
from datetime import datetime


class EmailSender(ABC):
    """Outgoing mail.

    Sending is synchronous for now: a queue only pays off once
    notifications-api exists.
    """

    @abstractmethod
    async def send_verification(self, *, to: str, verification_url: str) -> None: ...

    @abstractmethod
    async def send_password_reset(self, *, to: str, reset_url: str) -> None: ...


class RateLimiter(ABC):
    """Counter with an expiry window.

    The window opens on the first mark and the marks that follow do not extend
    it, so whoever hits the limit gets out after the configured time instead of
    being locked out forever.
    """

    @abstractmethod
    async def hit(self, key: str, *, window_seconds: int) -> int:
        """Count one mark and return how many there are in the window."""

    @abstractmethod
    async def count(self, key: str) -> int:
        """Marks so far. Zero once the window expired."""

    @abstractmethod
    async def reset(self, key: str) -> None:
        """Drop the counter so the next mark opens a fresh window."""


class SessionStore(ABC):
    """Revocation of access tokens that were already handed out.

    A JWT is self-contained and was never stored, so a session is not closed by
    deleting a row: what gets recorded is that a token, or every token of an
    account, stopped being valid before its own expiry.

    Two mechanisms because they answer different questions. Revoking one token
    closes a session on one device. Revoking an account has to be recorded as a
    cutoff instant, because the jtis handed out were never kept and there is no
    list to walk: a token counts as revoked when it was issued before the cutoff.
    """

    @abstractmethod
    async def revoke_token(self, jti: str, *, expires_at: datetime, now: datetime) -> None: ...

    @abstractmethod
    async def revoke_all(self, user_id: uuid.UUID, *, now: datetime, ttl_seconds: int) -> None: ...
