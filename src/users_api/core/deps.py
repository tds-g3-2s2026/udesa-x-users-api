"""Wiring shared by the routers.

Every feature builds its own service, but they all take the connections that
were opened once in the lifespan. This is the one place that knows where those
live, so a feature never reaches into app.state by hand.
"""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from users_api.core.db import session_scope


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """A transaction per request, committed when the handler returns."""
    async for session in session_scope(request.app.state.session_factory):
        yield session
