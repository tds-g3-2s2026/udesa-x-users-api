"""Administrator accounts: who creates them and under which rules.

E5-H2 only needs the first superadmin to exist. E5-H1 adds creation from the
panel with temporary passwords, and it belongs in this same class.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from users_api.app.models.user import Role, User
from users_api.app.repositories.users import UserRepository
from users_api.app.security import hash_password


@dataclass
class AdminService:
    users: UserRepository

    async def ensure_superadmin(self, *, email: str, handle: str, password: str) -> User | None:
        """Create the first superadmin, or do nothing if the address is taken.

        Idempotent on purpose: it runs on every deploy, before the API starts.
        An existing account is left untouched, whatever its role or password,
        so re-running the seed can never demote or reset anybody.
        """
        normalised_email = email.strip().lower()
        if await self.users.find_by_email(normalised_email) is not None:
            return None

        now = datetime.now(UTC)
        return await self.users.add(
            User(
                email=normalised_email,
                handle=handle.strip().lower(),
                password_hash=hash_password(password),
                role=Role.SUPERADMIN,
                # Nobody emails a verification link to the person who deploys
                # the system: the account is born verified.
                is_email_verified=True,
                terms_accepted=True,
                terms_accepted_at=now,
            )
        )
