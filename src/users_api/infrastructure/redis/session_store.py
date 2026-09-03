"""Revoked tokens, on Redis.

Every entry is written with a time to live: past the lifetime of an access token
there is nothing left to revoke, because anything issued earlier already expired
on its own. That is what keeps this from growing without bound.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from redis.asyncio import Redis

from users_api.core.ports import SessionStore


def revoked_token_key(jti: str) -> str:
    return f"revoked:jti:{jti}"


def revoked_sessions_key(user_id: uuid.UUID) -> str:
    return f"revoked:user:{user_id}"


@dataclass
class RedisSessionStore(SessionStore):
    redis: Redis

    async def revoke_token(self, jti: str, *, expires_at: datetime, now: datetime) -> None:
        ttl = int((expires_at - now).total_seconds())
        await self.redis.set(revoked_token_key(jti), "1", ex=ttl)

    async def revoke_all(self, user_id: uuid.UUID, *, now: datetime, ttl_seconds: int) -> None:
        # Stored as an instant and not as a list of jtis: the tokens handed out
        # were never kept, so there is nothing to enumerate. A token counts as
        # revoked when it was issued before this cutoff.
        await self.redis.set(
            revoked_sessions_key(user_id),
            int(now.timestamp()),
            ex=ttl_seconds,
        )
