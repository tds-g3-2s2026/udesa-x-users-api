"""Account numbers for the backoffice dashboard. Any administrator may read them."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime

from users_api.api.deps import AdministratorDep, UserRepositoryDep
from users_api.api.schemas.admin_metrics import (
    AccountMetricsResponse,
    DailyRegistrationsResponse,
    RegistrationMetricsResponse,
)
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


@router.get("/registrations")
async def registration_metrics(
    # With its offset, mandatory: where "today" starts depends on who asks.
    since: Annotated[AwareDatetime, Query()],
    _: AdministratorDep,
    service: ServiceDep,
) -> RegistrationMetricsResponse:
    """Accounts created per day from `since` until now, every day listed, zero included."""
    days = await service.registrations_per_day(since)
    return RegistrationMetricsResponse(
        days=[
            DailyRegistrationsResponse(date=one.day, registrations=one.registrations)
            for one in days
        ]
    )
