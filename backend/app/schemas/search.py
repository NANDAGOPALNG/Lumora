from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.retrieval.validation import DEFAULT_TOP_K, MAX_TOP_K


class SearchRequest(BaseModel):
    query: str = Field(..., description="Raw natural-language search query")
    workspace_id: UUID = Field(..., description="ID of the workspace to search within")
    document_id: Optional[UUID] = Field(
        default=None, description="Optionally restrict the search to a single document"
    )
    top_k: int = Field(
        default=DEFAULT_TOP_K,
        ge=1,
        le=MAX_TOP_K,
        description="Maximum number of results to return",
    )


class SearchSourceResponse(BaseModel):
    chunk_id: UUID
    document_id: UUID
    filename: str
    source: str
    chunk_index: int
    score: float
    content: Optional[str] = None


class SearchResponse(BaseModel):
    query: str = Field(..., description="The normalized query actually used for retrieval")
    context: str = Field(..., description="The assembled context text built from the top results")
    sources: List[SearchSourceResponse] = Field(
        default_factory=list, description="Structured citation metadata for the context, in order"
    )