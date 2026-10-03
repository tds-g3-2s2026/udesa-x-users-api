"""The account numbers the backoffice dashboard shows."""

from dataclasses import dataclass

from users_api.app.models.user import AccountStatus
from users_api.app.repositories.users import UserRepository


@dataclass(frozen=True)
class AccountMetrics:
    active_users: int
    # Accounts the reports froze and that wait for an administrator to decide.
    accounts_under_review: int


@dataclass
class MetricsService:
    users: UserRepository

    async def account_metrics(self) -> AccountMetrics:
        return AccountMetrics(
            active_users=await self.users.count_users(AccountStatus.ACTIVE),
            accounts_under_review=await self.users.count_users(AccountStatus.UNDER_REVIEW),
        )
