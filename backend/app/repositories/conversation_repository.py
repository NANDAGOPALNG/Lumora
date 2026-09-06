from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.conversation import Conversation
from app.repositories.base import BaseRepository


class ConversationRepository(BaseRepository[Conversation]):
    """Repository for Conversation rows.

    Every lookup that returns or mutates a specific conversation is
    scoped by `user_id` in the query itself (mirroring
    WorkspaceRepository.get_by_id_and_user /
    DocumentRepository.get_by_id_and_workspace_owner) - a conversation
    owned by a different user is never returned, regardless of how
    correct the caller's supplied UUID is.
    """

    def __init__(self, session: AsyncSession):
        super().__init__(session, Conversation)

    async def create_conversation(
        self, user_id: UUID, title: Optional[str] = None
    ) -> Conversation:
        """Create a new conversation owned by `user_id`."""
        conversation = Conversation(user_id=user_id, title=title)
        return await self.create(conversation)

    async def get_by_user(self, user_id: UUID) -> List[Conversation]:
        """List every conversation belonging to `user_id`, most recent first."""
        result = await self.session.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.created_at.desc())
        )
        return result.scalars().all()

    async def get_by_id_and_user(
        self, conversation_id: UUID, user_id: UUID
    ) -> Optional[Conversation]:
        """Fetch a conversation only if it belongs to `user_id`.

        The ownership check is part of the WHERE clause itself, so a
        conversation owned by a different user is never returned.
        """
        result = await self.session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def update_for_owner(
        self, conversation_id: UUID, user_id: UUID, update_data: dict
    ) -> Optional[Conversation]:
        """Update a conversation only if it belongs to `user_id`."""
        conversation = await self.get_by_id_and_user(conversation_id, user_id)
        if conversation is None:
            return None

        for key, value in update_data.items():
            setattr(conversation, key, value)

        await self.session.flush()
        await self.session.refresh(conversation)
        return conversation

    async def delete_for_owner(self, conversation_id: UUID, user_id: UUID) -> bool:
        """Delete a conversation only if it belongs to `user_id`.

        Its messages are removed along with it via the model's
        `cascade="all, delete-orphan"` relationship (see
        app/models/conversation.py) - no separate message cleanup is
        needed here.
        """
        conversation = await self.get_by_id_and_user(conversation_id, user_id)
        if conversation is None:
            return False

        await self.session.delete(conversation)
        await self.session.flush()
        return True
