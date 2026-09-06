from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.retrieval.validation import DEFAULT_TOP_K, MAX_TOP_K
from app.schemas.search import SearchSourceResponse


class ChatRequest(BaseModel):
    query: str = Field(..., description="Raw natural-language user question")
    workspace_id: UUID = Field(..., description="ID of the workspace to search within")
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
    sources: List[SearchSourceResponse] = Field(
        default_factory=list,
        description="Structured citation metadata for the sources the answer draws on, in order",
    )
