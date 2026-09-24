import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from users_api.api.health import router
from users_api.infrastructure.health import (
    DependencyStatus,
    build_report,
    check_postgres,
    check_redis,
)


class FakeConnection:
    def __init__(self, *, fails: bool) -> None:
        self.fails = fails

    async def execute(self, statement):
        if self.fails:
            raise ConnectionError("could not connect")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeEngine:
    def __init__(self, *, fails: bool = False) -> None:
        self.fails = fails

    def connect(self):
        return FakeConnection(fails=self.fails)


class FakeRedis:
    def __init__(self, *, fails: bool = False) -> None:
        self.fails = fails

    async def ping(self):
        if self.fails:
            raise ConnectionError("could not connect")
        return True


async def test_healthy_postgres_reports_ok():
    status = await check_postgres(FakeEngine())
    assert status.is_healthy


async def test_unreachable_postgres_reports_the_error():
    status = await check_postgres(FakeEngine(fails=True))
    assert not status.is_healthy
    assert "could not connect" in status.detail


async def test_healthy_redis_reports_ok():
    status = await check_redis(FakeRedis())
    assert status.is_healthy


async def test_unreachable_redis_reports_the_error():
    status = await check_redis(FakeRedis(fails=True))
    assert not status.is_healthy
    assert "could not connect" in status.detail


def test_all_dependencies_healthy_returns_200():
    body, status_code = build_report(
        [DependencyStatus("postgres", True), DependencyStatus("redis", True)]
    )
    assert status_code == 200
    assert body["status"] == "ok"
    assert body["dependencies"] == {"postgres": "ok", "redis": "ok"}


@pytest.mark.parametrize("failing", ["postgres", "redis"])
def test_a_single_failing_dependency_returns_503(failing):
    statuses = [
        DependencyStatus(name, name != failing, None if name != failing else "no connection")
        for name in ("postgres", "redis")
    ]
    body, status_code = build_report(statuses)
    assert status_code == 503
    assert body["status"] == "degraded"
    assert body["dependencies"][failing] == "no connection"


async def test_liveness_stays_healthy_when_readiness_loses_dependencies():
    app = FastAPI()
    app.include_router(router)
    app.state.engine = FakeEngine(fails=True)
    app.state.redis = FakeRedis(fails=True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        readiness = await client.get("/healthcheck")
        liveness = await client.get("/livez")

    assert readiness.status_code == 503
    assert liveness.status_code == 200


async def test_healthcheck_reports_the_running_version_even_when_degraded():
    app = FastAPI(version="1.2.3")
    app.include_router(router)
    app.state.engine = FakeEngine(fails=True)
    app.state.redis = FakeRedis(fails=True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/healthcheck")

    assert response.status_code == 503
    assert response.json()["version"] == "1.2.3"
