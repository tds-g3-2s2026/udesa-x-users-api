"""The account numbers the backoffice dashboard shows."""

import datetime
from dataclasses import dataclass

from users_api.app.errors import ProblemError
from users_api.app.models.user import AccountStatus
from users_api.app.repositories.users import UserRepository

ONE_DAY = datetime.timedelta(days=1)
# The dashboard draws a week. The cap only keeps a `since` far in the past from
# making the service build one entry per day since the year 1.
MAX_REGISTRATION_DAYS = 90


@dataclass(frozen=True)
class AccountMetrics:
    active_users: int
    # Accounts the reports froze and that wait for an administrator to decide.
    accounts_under_review: int


@dataclass(frozen=True)
class DailyRegistrations:
    # The day as the caller reads it: the date of its start, in the offset of `since`.
    day: datetime.date
    registrations: int


@dataclass
class MetricsService:
    users: UserRepository

    async def account_metrics(self) -> AccountMetrics:
        return AccountMetrics(
            active_users=await self.users.count_users(AccountStatus.ACTIVE),
            accounts_under_review=await self.users.count_users(AccountStatus.UNDER_REVIEW),
        )

    async def registrations_per_day(
        self, since: datetime.datetime, *, now: datetime.datetime | None = None
    ) -> list[DailyRegistrations]:
        """App accounts created per day from `since` until now, today included.

        Where a day starts depends on who asks, so days are counted from `since`
        itself, with its offset, instead of from the server's midnight. A day with
        no registrations is in the answer with zero, so a chart has no gaps. A
        `since` in the future has no days.
        """
        now = now or datetime.datetime.now(datetime.UTC)
        days = (now - since) // ONE_DAY + 1
        if days > MAX_REGISTRATION_DAYS:
            raise ProblemError(
                status=422,
                code="metrics-range-too-long",
                title="No se pudieron contar los registros",
                detail=f"El período no puede pasar de {MAX_REGISTRATION_DAYS} días",
            )
        if days <= 0:
            return []

        counts = await self.users.count_registrations_per_day(since, days)
        return [
            DailyRegistrations(
                day=(since + ONE_DAY * position).date(), registrations=counts.get(position, 0)
            )
            for position in range(days)
        ]
