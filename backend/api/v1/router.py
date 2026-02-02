from fastapi import APIRouter

from modules.analysis import router as analysis_router
from modules.compute import router as compute_router
from modules.config import router as config_router
from modules.datasource import router as datasource_router
from modules.health.routes import router as health_router
from modules.locks import router as locks_router
from modules.udf import router as udf_router

router = APIRouter(prefix='/v1')

router.include_router(analysis_router)
router.include_router(compute_router)
router.include_router(config_router)
router.include_router(datasource_router)
router.include_router(locks_router)
router.include_router(health_router)
router.include_router(udf_router)
