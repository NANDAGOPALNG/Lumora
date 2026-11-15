"""Dashboard API: GET /api/v1/dashboard/summary.

Requires an authenticated user. The user is taken only from the verified
token (`get_current_user`); no user id is accepted from the client, and
every query is scoped to that user in the repository layer.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.repositories.dashboard_repository import DashboardRepository
from app.schemas.dashboard import DashboardSummaryResponse
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def get_dashboard_service(
    session: AsyncSession = Depends(get_db, scope="function"),
) -> DashboardService:
    return DashboardService(DashboardRepository(session))


@router.get("/summary", response_model=DashboardSummaryResponse)
async def get_dashboard_summary(
    current_user: User = Depends(get_current_user),
    service: DashboardService = Depends(get_dashboard_service),
) -> DashboardSummaryResponse:
    return await service.get_summary(current_user.id)
