from typing import List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.conversation import Conversation
from app.models.message import Message
from app.repositories.base import BaseRepository


class MessageRepository(BaseRepository[Message]):
    """Repository for Message rows.

    Message itself carries no `user_id` (ownership lives one level up,
    on its parent Conversation), so - mirroring
    DocumentRepository.get_by_workspace / get_by_workspace_owner -
    this repository offers both a plain conversation-scoped lookup and
    a join-enforced one that checks the parent Conversation's
    `user_id` in the same query. Callers that have already verified
    conversation ownership (e.g. via
    ConversationRepository.get_by_id_and_user) may use the plain
    lookup; anywhere ownership hasn't already been checked, use the
    `_and_user` variant so a message never leaks across users purely
    because its conversation_id was guessed or reused.
    """

    def __init__(self, session: AsyncSession):
        super().__init__(session, Message)

    async def create_message(
        self, conversation_id: UUID, role: str, content: str
    ) -> Message:
        """Save a single message to `conversation_id`."""
        message = Message(conversation_id=conversation_id, role=role, content=content)
        return await self.create(message)

    async def get_by_conversation(self, conversation_id: UUID) -> List[Message]:
        """List all messages for `conversation_id`, oldest first.

        Does not itself check conversation ownership - use this only
        after the caller has already verified the conversation belongs
        to the requesting user.
        """
        result = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
        return result.scalars().all()

    async def get_by_conversation_and_user(
        self, conversation_id: UUID, user_id: UUID
    ) -> List[Message]:
        """List all messages for `conversation_id`, oldest first, but
        only if that conversation belongs to `user_id`.

        The ownership check is enforced via a join to Conversation in
        the query itself, not by fetching messages and checking
        ownership afterward. Returns an empty list both when the
        conversation has no messages and when it doesn't belong to
        `user_id` - callers that need to distinguish "empty" from
        "not yours" should check conversation ownership separately
        (e.g. via ConversationRepository.get_by_id_and_user) first.
        """
        result = await self.session.execute(
            select(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Message.conversation_id == conversation_id,
                Conversation.user_id == user_id,
            )
            .order_by(Message.created_at.asc())
        )
        return result.scalars().all()
