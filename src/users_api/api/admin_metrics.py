"""Account numbers for the backoffice dashboard. Any administrator may read them."""

from typing import Annotated

from fastapi import APIRouter, Depends

from users_api.api.deps import AdministratorDep, UserRepositoryDep
from users_api.api.schemas.admin_metrics import AccountMetricsResponse
from users_api.app.services.metrics import MetricsService

router = APIRouter(prefix="/admin/metrics", tags=["admin"])


async def get_metrics_service(users: UserRepositoryDep) -> MetricsService:
    return MetricsService(users=users)


ServiceDep = Annotated[MetricsService, Depends(get_metrics_service)]


@router.get("")
async def account_metrics(_: AdministratorDep, service: ServiceDep) -> AccountMetricsResponse:
    metrics = await service.account_metrics()
    return AccountMetricsResponse(
        active_users=metrics.active_users,
        accounts_under_review=metrics.accounts_under_review,
    )
