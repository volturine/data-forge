from fastapi import APIRouter

from core.error_handlers import handle_errors

from .schemas import HealthResponse
from .service import get_health_status

router = APIRouter(prefix='/health', tags=['health'])


@router.get('/', response_model=HealthResponse)
@handle_errors(operation='health check')
def check_health():
    return get_health_status()
