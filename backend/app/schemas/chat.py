from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.retrieval.validation import DEFAULT_TOP_K, MAX_TOP_K
from app.schemas.search import SearchSourceResponse


class ChatRequest(BaseModel):
    query: str = Field(..., description="Raw natural-language user question")
    workspace_id: UUID = Field(..., description="ID of the workspace to search within")
    conversation_id: Optional[UUID] = Field(
        default=None,
        description=(
            "Optionally continue an existing conversation. Omit to start a new "
            "conversation; the new conversation's id is returned in the response."
        ),
    )
    document_id: Optional[UUID] = Field(
        default=None, description="Optionally restrict retrieval to a single document"
    )
    top_k: int = Field(
        default=DEFAULT_TOP_K,
        ge=1,
        le=MAX_TOP_K,
        description="Maximum number of retrieved chunks to consider",
    )


class ChatResponse(BaseModel):
    answer: str = Field(..., description="The generated answer, grounded in the retrieved context")
    query: str = Field(..., description="The normalized query actually used for retrieval")
    conversation_id: UUID = Field(
        ...,
        description=(
            "The conversation this turn was recorded under - either the "
            "supplied conversation_id, or a newly created conversation's id "
            "when conversation_id was omitted"
        ),
    )
    sources: List[SearchSourceResponse] = Field(
        default_factory=list,
        description="Structured citation metadata for the sources the answer draws on, in order",
    )


class ConversationResponse(BaseModel):
    """A conversation's metadata only - no messages.

    Used for GET /chat/history, where returning every message for
    every conversation would be unnecessary for a list view.
    """

    id: UUID = Field(..., description="Conversation id")
    title: Optional[str] = Field(default=None, description="Conversation title, if any")
    created_at: datetime = Field(..., description="When the conversation was created")

    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    """A single message within a conversation."""

    id: UUID = Field(..., description="Message id")
    role: str = Field(..., description='"user" or "assistant"')
    content: str = Field(..., description="Message text")
    created_at: datetime = Field(..., description="When the message was created")

    model_config = ConfigDict(from_attributes=True)


class ConversationHistoryResponse(BaseModel):
    """A single conversation's metadata plus its messages, in
    chronological order. Used for GET /chat/{conversation_id}.
    """

    id: UUID = Field(..., description="Conversation id")
    title: Optional[str] = Field(default=None, description="Conversation title, if any")
    created_at: datetime = Field(..., description="When the conversation was created")
    messages: List[MessageResponse] = Field(
        default_factory=list,
        description="This conversation's messages, oldest first",
    )

    model_config = ConfigDict(from_attributes=True)
