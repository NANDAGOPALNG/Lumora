from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ActivityType = Literal["document_uploaded", "connector_synced", "conversation_created"]


class DashboardStats(BaseModel):
    workspaces: int = Field(..., ge=0)
    documents: int = Field(..., ge=0)
    indexed_chunks: int = Field(..., ge=0)
    conversations: int = Field(..., ge=0)


class DashboardActivity(BaseModel):
    # Stable, prefixed record id (e.g. "document:<uuid>") so ids from
    # different tables can never collide in the merged list.
    id: str
    type: ActivityType
    title: str
    description: str
    created_at: datetime
    workspace_id: Optional[UUID] = None
    link: Optional[str] = None


class DashboardSummaryResponse(BaseModel):
    stats: DashboardStats
    recent_activity: List[DashboardActivity]

    model_config = ConfigDict(from_attributes=True)
