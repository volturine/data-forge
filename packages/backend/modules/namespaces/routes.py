from fastapi import Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from backend_core.data_plane_client import client_from_settings
from backend_core.database import get_settings_db
from backend_core.error_handlers import handle_errors
from backend_core.namespace import list_namespaces, namespace_paths, normalize_namespace
from backend_core.namespace_storage import NAMESPACE_NAME_RULES, namespace_storage_plan
from backend_core.namespaces_service import list_runtime_namespaces, register_namespace
from modules.auth.dependencies import get_current_user
from modules.mcp.router import MCPRouter

router = MCPRouter(prefix='/namespaces', tags=['namespaces'])


class NamespaceListResponse(BaseModel):
    namespaces: list[str]


class NamespaceCreateRequest(BaseModel):
    name: str = Field(description=f'Product namespace (= S3 bucket). {NAMESPACE_NAME_RULES}')


class NamespaceStoragePlanResponse(BaseModel):
    name: str
    bucket: str
    uploads_root: str
    clean_root: str
    exports_root: str
    runtime_artifacts_root: str
    rules: str = NAMESPACE_NAME_RULES


class NamespaceResponse(BaseModel):
    name: str
    storage: NamespaceStoragePlanResponse
    created_bucket: bool


def _storage_response(name: str) -> NamespaceStoragePlanResponse:
    plan = namespace_storage_plan(name)
    return NamespaceStoragePlanResponse(
        name=plan.name,
        bucket=plan.bucket,
        uploads_root=plan.uploads_root,
        clean_root=plan.clean_root,
        exports_root=plan.exports_root,
        runtime_artifacts_root=plan.runtime_artifacts_root,
    )


def _provision_namespace_bucket(name: str) -> None:
    """Create the namespace S3 bucket if it does not exist yet."""
    client_from_settings().ensure_object_store_bucket(name)


@router.get('', response_model=NamespaceListResponse, mcp=True)
@handle_errors(operation='list namespaces')
def list_namespaces_endpoint(
    session: Session = Depends(get_settings_db),
) -> NamespaceListResponse:
    """List namespaces. Each name is an S3 bucket."""
    names = {*list_namespaces(), *list_runtime_namespaces(session)}
    return NamespaceListResponse(namespaces=sorted(names))


@router.get('/storage-plan', response_model=NamespaceStoragePlanResponse, mcp=True)
@handle_errors(operation='preview namespace storage plan', value_error_status=400)
def namespace_storage_plan_endpoint(
    name: str = Query(..., min_length=1, description='Proposed namespace name (= bucket)'),
) -> NamespaceStoragePlanResponse:
    """Preview the bucket and path roots for a namespace name. No side effects."""
    return _storage_response(normalize_namespace(name))


@router.post('', response_model=NamespaceResponse, mcp=True, dependencies=[Depends(get_current_user)])
@handle_errors(operation='create namespace', value_error_status=400)
def create_namespace_endpoint(
    request: NamespaceCreateRequest,
    session: Session = Depends(get_settings_db),
) -> NamespaceResponse:
    """Register a namespace and create its S3 bucket (name == bucket)."""
    name = normalize_namespace(request.name)
    storage = _storage_response(name)
    namespace_paths(name)
    _provision_namespace_bucket(name)
    register_namespace(session, name)
    return NamespaceResponse(name=name, storage=storage, created_bucket=True)
