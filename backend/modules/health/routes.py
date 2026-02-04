from fastapi import APIRouter

from .schemas import HealthResponse
from .service import get_health_status

router = APIRouter(prefix='/health', tags=['health'])


@router.get('/', response_model=HealthResponse)
def check_health():
    return get_health_status()
