"""Attempt counters, on Redis.

Redis is the right fit because every counter has to expire on its own: nobody
runs a job to unlock accounts, the key simply stops existing.
"""

from dataclasses import dataclass

from redis.asyncio import Redis

from users_api.app.repositories.rate_limiter import RateLimiter


@dataclass
class RedisRateLimiter(RateLimiter):
    redis: Redis

    async def hit(self, key: str, *, window_seconds: int) -> int:
        marks = await self.redis.incr(key)
        # The expiry is set only on the first mark, so later attempts do not
        # push the window forward and lock somebody out indefinitely.
        if marks == 1:
            await self.redis.expire(key, window_seconds)
        return marks

    async def count(self, key: str) -> int:
        marks = await self.redis.get(key)
        return int(marks) if marks is not None else 0

    async def reset(self, key: str) -> None:
        await self.redis.delete(key)
