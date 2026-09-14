"""Accounts, on PostgreSQL through SQLAlchemy.

This is the only place in the service that knows accounts live in a relational
table. It receives and returns the dataclass from the domain, so nothing above
it ever sees a row.

It does not commit: the transaction opens and closes once per request, in
`core/db.session_scope`. Committing here would break the atomicity of a
registration, where the account and its verification link have to land together
or not at all.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from users_api.app.models.user import FeedLanguage, ProfileVisibility, Role, User
from users_api.app.repositories.users import UserRepository
from users_api.infrastructure.database.models import UserModel


def to_domain(row: UserModel) -> User:
    return User(
        id=row.id,
        email=row.email,
        handle=row.handle,
        password_hash=row.password_hash,
        role=Role(row.role),
        must_change_password=row.must_change_password,
        temporary_password_expires_at=row.temporary_password_expires_at,
        is_email_verified=row.is_email_verified,
        is_suspended=row.is_suspended,
        deleted_at=row.deleted_at,
        terms_accepted=row.terms_accepted,
        terms_accepted_at=row.terms_accepted_at,
        created_at=row.created_at,
        display_name=row.display_name,
        bio=row.bio,
        profile_visibility=ProfileVisibility(row.profile_visibility),
        feed_language=FeedLanguage(row.feed_language),
    )


@dataclass
class SqlAlchemyUserRepository(UserRepository):
    session: AsyncSession

    async def add(self, user: User) -> User:
        row = UserModel(
            email=user.email,
            handle=user.handle,
            password_hash=user.password_hash,
            role=user.role.value,
            must_change_password=user.must_change_password,
            temporary_password_expires_at=user.temporary_password_expires_at,
            is_email_verified=user.is_email_verified,
            is_suspended=user.is_suspended,
            deleted_at=user.deleted_at,
            terms_accepted=user.terms_accepted,
            terms_accepted_at=user.terms_accepted_at,
            display_name=user.display_name,
            bio=user.bio,
            profile_visibility=user.profile_visibility.value,
            feed_language=user.feed_language.value,
        )
        self.session.add(row)
        # Flushed and not committed: the caller needs the assigned id to hang
        # the verification token off it, inside the same transaction.
        await self.session.flush()
        return to_domain(row)

    async def get(self, user_id: uuid.UUID) -> User | None:
        row = await self.session.get(UserModel, user_id)
        return to_domain(row) if row is not None else None

    async def find_by_identifier(self, identifier: str) -> User | None:
        row = await self.session.scalar(
            select(UserModel).where(
                or_(UserModel.email == identifier, UserModel.handle == identifier)
            )
        )
        return to_domain(row) if row is not None else None

    async def find_by_email(self, email: str) -> User | None:
        row = await self.session.scalar(select(UserModel).where(UserModel.email == email))
        return to_domain(row) if row is not None else None

    async def exists_with_email_or_handle(self, email: str, handle: str) -> bool:
        taken = await self.session.scalar(
            select(UserModel.id).where(or_(UserModel.email == email, UserModel.handle == handle))
        )
        return taken is not None

    async def update(self, user: User) -> None:
        row = await self.session.get(UserModel, user.id)
        if row is None:
            return
        row.password_hash = user.password_hash
        row.role = user.role.value
        row.must_change_password = user.must_change_password
        row.temporary_password_expires_at = user.temporary_password_expires_at
        row.is_email_verified = user.is_email_verified
        row.is_suspended = user.is_suspended
        row.deleted_at = user.deleted_at
        row.display_name = user.display_name
        row.bio = user.bio
        row.profile_visibility = user.profile_visibility.value
        row.feed_language = user.feed_language.value
