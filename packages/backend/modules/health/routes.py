from fastapi import APIRouter

from backend_core.error_handlers import handle_errors

from .schemas import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/", response_model=HealthResponse)
@handle_errors(operation="health check")
def check_health() -> HealthResponse:
    return HealthResponse(status="ok", version="0.1.0")
