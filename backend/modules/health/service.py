from .schemas import HealthResponse


def get_health_status() -> HealthResponse:
    return HealthResponse(status='ok', version='0.1.0')
