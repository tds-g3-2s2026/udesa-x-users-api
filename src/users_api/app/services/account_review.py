"""Putting an account under review after enough reports (E3-H5).

The reports live in posts-api, which counts them and calls here once an account
crosses the threshold (ADR-011). This side only owns what follows: the account
stops being usable and every session it has open ends.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from users_api.app.errors import ProblemError
from users_api.app.models.user import AccountStatus
from users_api.app.repositories.sessions import SessionStore
from users_api.app.repositories.users import UserRepository
from users_api.config.settings import Settings


@dataclass
class AccountReviewService:
    users: UserRepository
    sessions: SessionStore
    settings: Settings

    async def put_under_review(self, user_id: uuid.UUID) -> None:
        """Idempotent: posts-api calls again with every report past the threshold.

        Only an active account moves. One already under review has nothing
        left to do, and a suspended one keeps the stronger state an
        administrator chose for it.
        """
        user = await self.users.get(user_id)
        if user is None:
            raise ProblemError(
                status=404,
                code="account-not-found",
                title="No se pudo poner la cuenta en revisión",
                detail="La cuenta no existe",
            )
        if user.status is not AccountStatus.ACTIVE:
            return

        user.status = AccountStatus.UNDER_REVIEW
        await self.users.update(user)

        # The same cutoff a password change writes, so every token issued up to
        # this second is refused. Its life only needs to match the longest a
        # token can live: past that, the tokens it guards have expired anyway,
        # and the account can no longer get new ones.
        await self.sessions.revoke_all(
            user.id,
            now=datetime.now(UTC),
            ttl_seconds=self.settings.access_token_minutes * 60,
        )
