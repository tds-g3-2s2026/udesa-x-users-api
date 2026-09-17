import logging

import pytest
from httpx import ASGITransport, AsyncClient

from tests.integration.helpers import Api


@pytest.fixture
async def api(clean_state, caplog):
    """The app, driven over ASGI with its real lifespan, on a clean database."""
    from users_api.main import app

    caplog.set_level(logging.INFO)
    async with (
        # The prefix travels in the base URL so each test keeps writing the path
        # it cares about, and the request that goes out is the real one.
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api") as client,
        app.router.lifespan_context(app),
    ):
        yield Api(client, app, caplog)
