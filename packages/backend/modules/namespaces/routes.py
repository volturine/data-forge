from core.namespace import list_namespaces
from pydantic import BaseModel

from backend_core.error_handlers import handle_errors
from modules.mcp.router import MCPRouter

router = MCPRouter(prefix="/namespaces", tags=["namespaces"])


class NamespaceListResponse(BaseModel):
    namespaces: list[str]


@router.get("", response_model=NamespaceListResponse, mcp=True)
@handle_errors(operation="list namespaces")
def list_namespaces_endpoint() -> NamespaceListResponse:
    """List all available namespaces. Namespaces isolate data directories and databases."""
    return NamespaceListResponse(namespaces=list_namespaces())
