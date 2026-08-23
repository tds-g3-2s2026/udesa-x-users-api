import os

import pytest
from httpx import ASGITransport, AsyncClient

# Needs PostgreSQL and Valkey running. docker/docker-compose.dev.yml provides both.
pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("VALKEY_URL"),
    reason="requires DATABASE_URL and VALKEY_URL pointing at real services",
)


async def test_healthcheck_returns_ok_when_dependencies_are_up():
    from users_api.main import app

    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        response = await client.get("/healthcheck")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["dependencies"] == {"postgres": "ok", "valkey": "ok"}
