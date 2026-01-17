from fastapi import APIRouter

from modules.analysis import router as analysis_router
from modules.compute import router as compute_router
from modules.datasource import router as datasource_router
from modules.results import router as results_router
from modules.health.routes import router as health_router

router = APIRouter(prefix='/v1')

router.include_router(analysis_router)
router.include_router(compute_router)
router.include_router(datasource_router)
router.include_router(results_router)
router.include_router(health_router)
