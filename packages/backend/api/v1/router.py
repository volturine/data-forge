from fastapi import APIRouter

from modules.ai import router as ai_router
from modules.analysis.routes import router as analysis_router
from modules.analysis_versions.routes import router as analysis_versions_router
from modules.auth import router as auth_router
from modules.chat import router as chat_router
from modules.compute.routes import router as compute_router
from modules.config import router as config_router
from modules.datasource.routes import router as datasource_router
from modules.engine_runs.routes import router as engine_runs_router
from modules.health.routes import router as health_router
from modules.healthcheck import router as healthcheck_router
from modules.locks import router as locks_router
from modules.logs import router as logs_router
from modules.mcp.routes import router as mcp_router
from modules.namespaces import router as namespaces_router
from modules.runtime_overview import router as runtime_overview_router
from modules.scheduler import router as scheduler_router
from modules.settings import router as settings_router
from modules.telegram import router as telegram_router
from modules.udf import router as udf_router

router = APIRouter(prefix="/v1")


router.include_router(ai_router)
router.include_router(analysis_router)
router.include_router(analysis_versions_router)
router.include_router(auth_router)
router.include_router(chat_router)
router.include_router(compute_router)
router.include_router(config_router)
router.include_router(datasource_router)
router.include_router(engine_runs_router)
router.include_router(healthcheck_router)
router.include_router(health_router)
router.include_router(logs_router)
router.include_router(locks_router)
router.include_router(mcp_router)
router.include_router(namespaces_router)
router.include_router(runtime_overview_router)
router.include_router(settings_router)
router.include_router(telegram_router)
router.include_router(udf_router)
router.include_router(scheduler_router)
