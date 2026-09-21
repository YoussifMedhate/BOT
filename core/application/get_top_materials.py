from __future__ import annotations

from core.application.analytics_service import analytics_repository
from core.domain.analytics import MaterialStat


async def get_top_materials(limit: int = 10) -> list[MaterialStat]:
    return await analytics_repository.get_top_materials(limit)
