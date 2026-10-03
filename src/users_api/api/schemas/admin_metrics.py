from pydantic import BaseModel


class AccountMetricsResponse(BaseModel):
    active_users: int
    accounts_under_review: int
