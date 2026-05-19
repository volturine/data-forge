from core.database import get_settings_db
from core.namespace import list_namespaces, namespace_paths, normalize_namespace
from core.namespaces_service import list_runtime_namespaces, register_namespace
from fastapi import Depends
from pydantic import BaseModel
from sqlmodel import Session

from backend_core.error_handlers import handle_errors
from modules.mcp.router import MCPRouter

router = MCPRouter(prefix="/namespaces", tags=["namespaces"])


class NamespaceListResponse(BaseModel):
    namespaces: list[str]


class NamespaceCreateRequest(BaseModel):
    name: str


class NamespaceResponse(BaseModel):
    name: str


@router.get("", response_model=NamespaceListResponse, mcp=True)
@handle_errors(operation="list namespaces")
def list_namespaces_endpoint(
    session: Session = Depends(get_settings_db),
) -> NamespaceListResponse:
    """List all available namespaces. Namespaces isolate data directories and databases."""
    names = {*list_namespaces(), *list_runtime_namespaces(session)}
    return NamespaceListResponse(namespaces=sorted(names))


@router.post("", response_model=NamespaceResponse, mcp=True)
@handle_errors(operation="create namespace", value_error_status=400)
def create_namespace_endpoint(
    request: NamespaceCreateRequest,
    session: Session = Depends(get_settings_db),
) -> NamespaceResponse:
    """Register a namespace so it is immediately available across the app."""
    name = normalize_namespace(request.name)
    namespace_paths(name)
    register_namespace(session, name)
    return NamespaceResponse(name=name)
