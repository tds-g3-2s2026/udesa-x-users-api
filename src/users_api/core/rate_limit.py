"""Reusable counter with an expiry window, on top of Redis.

Several flows need the same shape of limit: the login lockout, the cap on reset
requests and, later, the admin login. Keeping one implementation means the
window semantics are decided once.

The window starts on the first mark and is not extended by the ones that follow,
so a caller that keeps hitting the limit still gets out after the configured
time instead of being locked out forever.
"""

from redis.asyncio import Redis


async def hit(redis: Redis, key: str, *, window_seconds: int) -> int:
    """Count one mark and return how many there are in the current window."""
    marks = await redis.incr(key)
    if marks == 1:
        await redis.expire(key, window_seconds)
    return marks


async def count(redis: Redis, key: str) -> int:
    """Marks so far in the current window. Zero once the window expired."""
    marks = await redis.get(key)
    return int(marks) if marks is not None else 0


async def reset(redis: Redis, key: str) -> None:
    """Drop the counter, so the next mark starts a fresh window."""
    await redis.delete(key)
