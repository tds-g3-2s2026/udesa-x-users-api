"""Counting attempts, without naming where the count is kept."""

from abc import ABC, abstractmethod


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
