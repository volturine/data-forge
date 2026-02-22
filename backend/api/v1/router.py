from fastapi import APIRouter

from modules.ai import router as ai_router
from modules.analysis import router as analysis_router
from modules.analysis_versions import router as analysis_versions_router
from modules.compute import router as compute_router
from modules.config import router as config_router
from modules.datasource import router as datasource_router
from modules.engine_runs import router as engine_runs_router
from modules.health.routes import router as health_router
from modules.healthcheck import router as healthcheck_router
from modules.locks import router as locks_router
from modules.logs import router as logs_router
from modules.namespaces import router as namespaces_router
from modules.scheduler import router as scheduler_router
from modules.settings import router as settings_router
from modules.telegram import router as telegram_router
from modules.udf import router as udf_router

router = APIRouter(prefix='/v1')


router.include_router(ai_router)
router.include_router(analysis_router)
router.include_router(analysis_versions_router)
router.include_router(compute_router)
router.include_router(config_router)
router.include_router(datasource_router)
router.include_router(engine_runs_router)
router.include_router(healthcheck_router)
router.include_router(locks_router)
router.include_router(health_router)
router.include_router(logs_router)
router.include_router(namespaces_router)
router.include_router(settings_router)
router.include_router(telegram_router)
router.include_router(udf_router)
router.include_router(scheduler_router)
