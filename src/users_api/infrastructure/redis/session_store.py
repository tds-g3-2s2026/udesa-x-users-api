"""Revoked tokens, on Redis.

Every entry is written with a time to live: past the lifetime of an access token
there is nothing left to revoke, because anything issued earlier already expired
on its own. That is what keeps this from growing without bound.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis

from users_api.app.repositories.sessions import SessionStore


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

    async def is_token_revoked(self, jti: str) -> bool:
        return await self.redis.exists(revoked_token_key(jti)) == 1

    async def revoked_before(self, user_id: uuid.UUID) -> datetime | None:
        cutoff = await self.redis.get(revoked_sessions_key(user_id))
        if cutoff is None:
            return None
        # Written as a Unix timestamp, read back as an aware instant so the
        # caller compares it against the token's iat without juggling formats.
        return datetime.fromtimestamp(int(cutoff), tz=UTC)
