"""Revocation of issued access tokens, on Redis.

A JWT is self-contained and the server never stored it, so a session cannot be
closed by deleting a row: what gets recorded is that a token, or every token of
an account, stopped being valid before it expired on its own.

There are two mechanisms because they answer different questions:

- one token, by its jti, which is what closing a session on one device needs;
- every token of an account at once, recorded as a cutoff instant, because the
  jtis that were handed out were never stored and there is no list to walk. A
  token counts as revoked when its iat is older than that cutoff.

Both entries expire by themselves: past the lifetime of an access token there is
nothing left to revoke, since anything issued before already expired.

Plain functions and not a service, so any flow that has to revoke —logging out,
resetting a forgotten password, changing a known one— uses the same code.
"""

import uuid
from datetime import datetime

from redis.asyncio import Redis


def revoked_token_key(jti: str) -> str:
    return f"revoked:jti:{jti}"


def revoked_sessions_key(user_id: uuid.UUID) -> str:
    return f"revoked:user:{user_id}"


async def revoke_token(redis: Redis, jti: str, *, expires_at: datetime, now: datetime) -> None:
    """Revoke a single token until the moment it would have expired anyway."""
    ttl = int((expires_at - now).total_seconds())
    await redis.set(revoked_token_key(jti), "1", ex=ttl)


async def revoke_all_sessions(
    redis: Redis, user_id: uuid.UUID, *, now: datetime, access_token_minutes: int
) -> None:
    """Invalidate every token issued for this account before now."""
    await redis.set(
        revoked_sessions_key(user_id),
        int(now.timestamp()),
        ex=access_token_minutes * 60,
    )
