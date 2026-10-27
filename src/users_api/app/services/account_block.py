"""An administrator blocking an app account (E5-H5).

Blocking is `suspended`, the state `deny_blocked_account` already refuses on
every login and every request. What this adds is the decision itself: who took
it, why, and every session the account had open ending at once. posts-api reads
the same revocation marks (ADR-014), so the block reaches it without a call.

There is no unblocking yet: the story does not ask for it, and the team decides
whether it goes in S10.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from users_api.app.errors import ProblemError
from users_api.app.models.user import AccountStatus, User
from users_api.app.repositories.sessions import SessionStore
from users_api.app.repositories.tokens import RefreshTokenRepository
from users_api.app.repositories.users import UserRepository
from users_api.app.services.audit import AuditLog
from users_api.config.settings import Settings

USER_BLOCKED = "user.blocked"


@dataclass
class AccountBlockService:
    users: UserRepository
    sessions: SessionStore
    refresh_tokens: RefreshTokenRepository
    audit: AuditLog
    settings: Settings

    async def block(self, administrator: User, user_id: uuid.UUID, reason: str) -> None:
        """Suspend the account with `reason` and end every session it has open.

        `reason` arrives stripped and within its limits: the request schema
        refuses a missing or blank one before this runs (CA.1).
        """
        user = await self.users.get(user_id)
        if user is None or user.deleted_at is not None:
            raise ProblemError(
                status=404,
                code="account-not-found",
                title="No se pudo bloquear la cuenta",
                detail="La cuenta no existe",
            )
        if user.is_administrator:
            # Otherwise a moderator could lock a superadmin out of the backoffice.
            raise ProblemError(
                status=422,
                code="administrator-cannot-be-blocked",
                title="No se pudo bloquear la cuenta",
                detail="Las cuentas de administradores no se bloquean",
            )
        if user.status is AccountStatus.SUSPENDED:
            # Already blocked: a second administrator does not replace the reason
            # or the moment of the first, and its sessions already ended then.
            return

        # An account under review is blocked too: the administrator's decision
        # replaces the one the reports took, and E5-H7 must not reactivate it.
        now = datetime.now(UTC)
        user.change_status(AccountStatus.SUSPENDED, at=now, reason=reason)
        await self.users.update(user)
        await self.audit.record(administrator.id, USER_BLOCKED, "user", user.id, {"reason": reason})
        await self.refresh_tokens.revoke_all(user.id, revoked_at=now)

        # Last, once every database write is in: if the cutoff cannot be written
        # the request fails and the transaction rolls back, so the account is
        # never left blocked with its tokens still working.
        await self.sessions.revoke_all(
            user.id,
            now=now,
            ttl_seconds=self.settings.access_token_minutes * 60,
        )
