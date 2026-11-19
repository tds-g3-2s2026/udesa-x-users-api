import datetime

from pydantic import BaseModel


class AccountMetricsResponse(BaseModel):
    active_users: int
    accounts_under_review: int


class DailyRegistrationsResponse(BaseModel):
    date: datetime.date
    registrations: int


class RegistrationMetricsResponse(BaseModel):
    days: list[DailyRegistrationsResponse]
