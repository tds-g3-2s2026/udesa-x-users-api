"""Accounts, on PostgreSQL through SQLAlchemy.

This is the only place in the service that knows accounts live in a relational
table. It receives and returns the dataclass from the domain, so nothing above
it ever sees a row.

It does not commit: the transaction opens and closes once per request, in
`core/db.session_scope`. Committing here would break the atomicity of a
registration, where the account and its verification link have to land together
or not at all.
"""

import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from users_api.app.errors import ProblemError
from users_api.app.models.search import SEARCH_BATCH_SIZE, SearchCandidate
from users_api.app.models.user import (
    AccountStatus,
    FeedLanguage,
    ProfileVisibility,
    Role,
    User,
)
from users_api.app.repositories.users import UserRepository
from users_api.infrastructure.database.models import UserModel


def escape_like(fragment: str) -> str:
    """So a `%` or `_` typed in the search box matches itself and not anything."""
    return fragment.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def encode_cursor(row: UserModel) -> str:
    """The position a page ends on: the keyset the search orders by.

    Built and read only here, because its content is this query's ordering.
    Above this module it is an opaque string the client echoes back.
    """
    raw = f"{row.created_at.isoformat()}|{row.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(value: str) -> tuple[datetime, uuid.UUID]:
    try:
        at, last_id = base64.urlsafe_b64decode(value.encode()).decode().split("|")
        timestamp = datetime.fromisoformat(at)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Cursor timestamp requires a timezone")
        timestamp = timestamp.astimezone(UTC)
        return timestamp, uuid.UUID(last_id)
    except (ValueError, OverflowError, binascii.Error, UnicodeDecodeError) as error:
        # A tampered or stale cursor is the client's mistake, not a 500.
        raise ProblemError(
            status=400,
            code="invalid-cursor",
            title="Cursor inválido",
            detail="El cursor no tiene un formato reconocible",
        ) from error


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
        status=AccountStatus(row.status),
        status_reason=row.status_reason,
        status_changed_at=row.status_changed_at,
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
            status=user.status.value,
            status_reason=user.status_reason,
            status_changed_at=user.status_changed_at,
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

    async def search_user_accounts(
        self, fragment: str, *, cursor: str | None, limit: int
    ) -> tuple[list[User], str | None]:
        pattern = f"%{escape_like(fragment)}%"
        statement = select(UserModel).where(
            UserModel.role == Role.USER.value,
            UserModel.deleted_at.is_(None),
            or_(
                UserModel.email.ilike(pattern, escape="\\"),
                UserModel.handle.ilike(pattern, escape="\\"),
            ),
        )
        if cursor is not None:
            at, last_id = decode_cursor(cursor)
            # A row comparison, so an account created in the same instant as
            # the last one shown is neither repeated nor skipped.
            statement = statement.where(tuple_(UserModel.created_at, UserModel.id) < (at, last_id))
        # One past the page: getting it back is what says there is a next one.
        rows = list(
            await self.session.scalars(
                statement.order_by(UserModel.created_at.desc(), UserModel.id.desc()).limit(
                    limit + 1
                )
            )
        )
        page = rows[:limit]
        next_cursor = encode_cursor(page[-1]) if len(rows) > limit else None
        return [to_domain(row) for row in page], next_cursor

    async def search_public_accounts(
        self, fragment: str, *, handle_only: bool, cursor: str | None
    ) -> list[SearchCandidate]:
        pattern = f"%{escape_like(fragment)}%"
        match = UserModel.handle.ilike(pattern, escape="\\")
        if not handle_only:
            match = or_(match, UserModel.display_name.ilike(pattern, escape="\\"))
        statement = select(UserModel).where(
            UserModel.role == Role.USER.value, UserModel.deleted_at.is_(None), match
        )
        if cursor is not None:
            statement = statement.where(
                tuple_(UserModel.created_at, UserModel.id) < decode_cursor(cursor)
            )
        rows = await self.session.scalars(
            statement.order_by(UserModel.created_at.desc(), UserModel.id.desc()).limit(
                SEARCH_BATCH_SIZE
            )
        )
        return [SearchCandidate(to_domain(row), encode_cursor(row)) for row in rows]

    async def list_administrators(self) -> list[User]:
        rows = await self.session.scalars(
            select(UserModel)
            .where(UserModel.role != Role.USER.value, UserModel.deleted_at.is_(None))
            .order_by(UserModel.created_at)
        )
        return [to_domain(row) for row in rows]

    async def count_users(self, status: AccountStatus) -> int:
        return await self.session.scalar(
            select(func.count())
            .select_from(UserModel)
            .where(
                UserModel.role == Role.USER.value,
                UserModel.status == status.value,
                UserModel.is_email_verified.is_(True),
                UserModel.deleted_at.is_(None),
            )
        )

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
        row.status = user.status.value
        row.status_reason = user.status_reason
        row.status_changed_at = user.status_changed_at
        row.deleted_at = user.deleted_at
        row.display_name = user.display_name
        row.bio = user.bio
        row.profile_visibility = user.profile_visibility.value
        row.feed_language = user.feed_language.value
