from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from users_api.infrastructure.health import build_report, check_postgres, check_redis

router = APIRouter(tags=["health"])


@router.get("/healthcheck")
async def healthcheck(request: Request) -> JSONResponse:
    """Check PostgreSQL and Redis, and report the version that is running."""
    state = request.app.state
    statuses = [
        await check_postgres(state.engine),
        await check_redis(state.redis),
    ]
    body, status_code = build_report(statuses)
    return JSONResponse({**body, "version": request.app.version}, status_code=status_code)


@router.get("/livez")
async def livez() -> dict[str, str]:
    """Liveness probe: report process alive without checking dependencies."""
    return {"status": "ok"}
