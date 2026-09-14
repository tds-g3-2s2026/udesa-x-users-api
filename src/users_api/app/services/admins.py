"""Administrator accounts: who creates them and under which rules.

E5-H2 only needs the first superadmin to exist. E5-H1 adds creation from the
panel with temporary passwords, and it belongs in this same class.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from users_api.app.errors import ProblemError
from users_api.app.models.user import Role, User
from users_api.app.repositories.users import UserRepository
from users_api.app.security import generate_temporary_password, hash_password
from users_api.config.settings import Settings

# How long a temporary password lasts. Not a setting: E5-H1 fixes it at a day,
# and a credential that somebody dictated should not be stretchable from the
# environment.
TEMPORARY_PASSWORD_HOURS = 24


@dataclass
class AdminService:
    users: UserRepository
    settings: Settings

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

    async def create_administrator(
        self, *, email: str, handle: str, role: Role
    ) -> tuple[User, str]:
        """Create an administrator account from the panel.

        Returns the account together with its temporary password in clear.
        That is the only moment the password exists outside its hash: there is
        no mail service yet, so whoever created the account reads it once on
        screen and passes it on. The stored copy is a hash like any other.
        """
        normalised_email = email.strip().lower()
        normalised_handle = handle.strip().lower()

        self.deny_email_outside_the_authorized_domain(normalised_email)

        if await self.users.exists_with_email_or_handle(normalised_email, normalised_handle):
            raise ProblemError(
                status=409,
                code="account-already-exists",
                title="No se pudo crear la cuenta",
                detail="El email o el nombre de usuario ya están en uso",
            )

        temporary_password = generate_temporary_password()
        now = datetime.now(UTC)
        user = await self.users.add(
            User(
                email=normalised_email,
                handle=normalised_handle,
                password_hash=hash_password(temporary_password),
                role=role,
                # The whole point: the owner did not choose this password and
                # cannot keep it.
                must_change_password=True,
                temporary_password_expires_at=now + timedelta(hours=TEMPORARY_PASSWORD_HOURS),
                # There is nobody to email a verification link to, the same
                # reason the seeded superadmin is born verified.
                is_email_verified=True,
                terms_accepted=True,
                terms_accepted_at=now,
            )
        )
        return user, temporary_password

    def deny_email_outside_the_authorized_domain(self, email: str) -> None:
        """Keep administrator accounts inside the institution, when asked to.

        With no domain configured there is no restriction, which is what makes
        this rule optional rather than something to switch off.
        """
        domain = self.settings.administrator_email_domain.strip().lower().lstrip("@")
        if domain and not email.endswith(f"@{domain}"):
            raise ProblemError(
                status=400,
                code="email-domain-not-allowed",
                title="No se pudo crear la cuenta",
                detail=f"El correo de un administrador tiene que ser del dominio @{domain}",
            )

    async def reset_temporary_password(self, user_id: uuid.UUID) -> tuple[User, str]:
        """Hand out a new temporary password for an account still owing one.

        The usual reason is that the first one expired unused. An account
        whose owner already chose a password is refused: replacing it would be
        taking the account away from them, which is not what this is for.
        """
        user = await self.users.get(user_id)
        if user is None:
            raise ProblemError(
                status=404,
                code="account-not-found",
                title="No se pudo regenerar la contraseña",
                detail="La cuenta no existe",
            )

        if not user.must_change_password:
            raise ProblemError(
                status=409,
                code="password-already-chosen",
                title="No se pudo regenerar la contraseña",
                detail="La cuenta ya eligió su propia contraseña",
            )

        temporary_password = generate_temporary_password()
        user.password_hash = hash_password(temporary_password)
        user.temporary_password_expires_at = datetime.now(UTC) + timedelta(
            hours=TEMPORARY_PASSWORD_HOURS
        )
        await self.users.update(user)
        return user, temporary_password

    async def list_administrators(self) -> list[User]:
        return await self.users.list_administrators()
