from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from users_api.config import get_settings
from users_api.health import build_report, check_postgres, check_valkey


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Connections are opened once and shared. Creating an engine per request
    # exhausts the PostgreSQL pool as soon as there is any load.
    settings = get_settings()
    app.state.engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    app.state.valkey = Redis.from_url(settings.valkey_url)
    yield
    await app.state.engine.dispose()
    await app.state.valkey.aclose()


app = FastAPI(title="UdeSA-X Users API", version="0.1.0", lifespan=lifespan)


@app.get("/healthcheck", tags=["health"])
async def healthcheck() -> JSONResponse:
    """Check PostgreSQL and Valkey before reporting the service as healthy."""
    statuses = [
        await check_postgres(app.state.engine),
        await check_valkey(app.state.valkey),
    ]
    body, status_code = build_report(statuses)
    return JSONResponse(body, status_code=status_code)
