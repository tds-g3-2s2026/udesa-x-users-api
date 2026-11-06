"""The feedback messages, on PostgreSQL through SQLAlchemy."""

from dataclasses import asdict, dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from users_api.app.models.feedback import Feedback
from users_api.app.repositories.feedback import FeedbackRepository
from users_api.infrastructure.database.models import FeedbackModel


@dataclass
class SqlAlchemyFeedbackRepository(FeedbackRepository):
    session: AsyncSession

    async def add(self, feedback: Feedback) -> None:
        self.session.add(FeedbackModel(**asdict(feedback)))
