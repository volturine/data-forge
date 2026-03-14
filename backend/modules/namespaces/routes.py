from fastapi import APIRouter
from pydantic import BaseModel

from core.namespace import list_namespaces
from modules.mcp.decorators import deterministic_tool

router = APIRouter(prefix='/namespaces', tags=['namespaces'])


class NamespaceListResponse(BaseModel):
    namespaces: list[str]


@router.get('', response_model=NamespaceListResponse)
@deterministic_tool
def list_namespaces_endpoint() -> NamespaceListResponse:
    return NamespaceListResponse(namespaces=list_namespaces())
