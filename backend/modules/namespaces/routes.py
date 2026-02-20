from fastapi import APIRouter
from pydantic import BaseModel

from core.namespace import list_namespaces

router = APIRouter(prefix='/namespaces', tags=['namespaces'])


class NamespaceListResponse(BaseModel):
    namespaces: list[str]


@router.get('', response_model=NamespaceListResponse)
def list_namespaces_endpoint() -> NamespaceListResponse:
    return NamespaceListResponse(namespaces=list_namespaces())
