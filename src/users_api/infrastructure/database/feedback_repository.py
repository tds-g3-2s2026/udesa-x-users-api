"""The feedback messages, on PostgreSQL through SQLAlchemy."""

import uuid
from dataclasses import asdict, dataclass

from sqlalchemy import and_, select, tuple_
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from users_api.app.models.feedback import Feedback, FeedbackStatus, InboxEntry
from users_api.app.repositories.feedback import FeedbackRepository
from users_api.infrastructure.database.models import FeedbackModel, UserModel

# The same keyset as the account search, creation date and then id, so its
# cursor is reused as it is.
from users_api.infrastructure.database.user_repository import decode_cursor, encode_cursor


def to_domain(row: FeedbackModel) -> Feedback:
    return Feedback(
        id=row.id,
        user_id=row.user_id,
        handle=row.handle,
        message=row.message,
        device_os=row.device_os,
        app_version=row.app_version,
        created_at=row.created_at,
        status=FeedbackStatus(row.status),
    )


@dataclass
class SqlAlchemyFeedbackRepository(FeedbackRepository):
    session: AsyncSession

    async def add(self, feedback: Feedback) -> None:
        self.session.add(FeedbackModel(**asdict(feedback)))

    async def list_by_status(
        self, status: FeedbackStatus, *, cursor: str | None, limit: int
    ) -> tuple[list[InboxEntry], str | None]:
        # A left join because the message outlives the account: a deleted
        # sender finds no row and the message is listed all the same.
        statement = (
            select(FeedbackModel, UserModel.id.is_not(None).label("account_available"))
            .outerjoin(
                UserModel,
                and_(UserModel.id == FeedbackModel.user_id, UserModel.deleted_at.is_(None)),
            )
            .where(FeedbackModel.status == status.value)
        )
        if cursor is not None:
            at, last_id = decode_cursor(cursor)
            statement = statement.where(
                tuple_(FeedbackModel.created_at, FeedbackModel.id) < (at, last_id)
            )
        # One past the page: getting it back is what says there is a next one.
        rows = (
            await self.session.execute(
                statement.order_by(FeedbackModel.created_at.desc(), FeedbackModel.id.desc()).limit(
                    limit + 1
                )
            )
        ).all()
        page = rows[:limit]
        next_cursor = encode_cursor(page[-1][0]) if len(rows) > limit else None
        return [InboxEntry(to_domain(row), available) for row, available in page], next_cursor

    async def advance(
        self,
        feedback_id: uuid.UUID,
        *,
        to: FeedbackStatus,
        from_any_of: frozenset[FeedbackStatus],
    ) -> bool:
        # One statement, so two administrators at once can never send a message
        # back: whoever arrives second finds it already past the allowed states.
        result = await self.session.execute(
            sql_update(FeedbackModel)
            .where(
                FeedbackModel.id == feedback_id,
                FeedbackModel.status.in_([state.value for state in from_any_of]),
            )
            .values(status=to.value)
        )
        if result.rowcount:
            return True
        found = await self.session.scalar(
            select(FeedbackModel.id).where(FeedbackModel.id == feedback_id)
        )
        return found is not None
