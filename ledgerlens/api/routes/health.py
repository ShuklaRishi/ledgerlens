from fastapi import APIRouter, Response, status

from ledgerlens.api.deps import AgentPoolDep, SettingsDep
from ledgerlens.schemas.health import HealthReport
from ledgerlens.services.health import check_health

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthReport)
def health(pool: AgentPoolDep, settings: SettingsDep, response: Response) -> HealthReport:
    report = check_health(pool, settings)
    if report.status == "down":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report
