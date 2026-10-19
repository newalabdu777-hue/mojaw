from datetime import datetime, timezone
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["operations"])


class HealthResponse(BaseModel):
    status: str
    service: str
    timestamp_utc: datetime
    mode: str


@router.get("/health/live", response_model=HealthResponse, summary="Liveness probe")
def liveness() -> HealthResponse:
    return HealthResponse(
        status="ok", service="school-management-api",
        timestamp_utc=datetime.now(timezone.utc), mode="starter",
    )


@router.get("/health/ready", response_model=HealthResponse, summary="Readiness probe")
def readiness() -> HealthResponse:
    # No external dependencies are wired in this starter. Add database and queue checks
    # here when their approved implementations are introduced.
    return HealthResponse(
        status="ready", service="school-management-api",
        timestamp_utc=datetime.now(timezone.utc), mode="starter-no-persistence",
    )
