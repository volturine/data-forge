from fastapi import APIRouter

from .v1 import analysis_router

router = APIRouter(analysis_router, prefix='/api')
