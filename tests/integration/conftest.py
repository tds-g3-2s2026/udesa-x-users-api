import pytest
from httpx import ASGITransport, AsyncClient

from tests.integration.helpers import Api

# Nothing listens on port 1: the connection is refused at once.
UNREACHABLE_BROKER = "amqp://users:users@127.0.0.1:1"


@pytest.fixture
async def api(clean_state, monkeypatch):
    """The app, driven over ASGI with its real lifespan, on a clean database.

    Its publisher points at a broker nobody listens on, so the events stay in
    the outbox for the tests to read instead of being published and deleted
    under their feet. It is also the situation the service has to survive.
    """
    from users_api import main
    from users_api.main import app

    settings = main.get_settings().model_copy(update={"rabbitmq_url": UNREACHABLE_BROKER})
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    async with (
        # The prefix travels in the base URL so each test keeps writing the path
        # it cares about, and the request that goes out is the real one.
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api") as client,
        app.router.lifespan_context(app),
    ):
        yield Api(client, app)
