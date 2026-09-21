import asyncio
import logging
import time
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from functools import partial

from fastapi import Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from backend_core.data_plane_client import client_from_settings
from backend_core.database import get_settings_db, initialize_namespace_db, run_settings_db
from backend_core.error_handlers import handle_errors
from backend_core.namespace import list_namespaces, namespace_paths, normalize_namespace
from backend_core.namespace_credentials_service import provision_namespace_engine_credentials
from backend_core.namespace_storage import NAMESPACE_NAME_RULES, namespace_storage_plan
from backend_core.namespaces_service import list_runtime_namespaces, register_namespace, runtime_namespace_exists
from modules.auth.dependencies import get_current_user
from modules.mcp.router import MCPRouter

router = MCPRouter(prefix='/namespaces', tags=['namespaces'])
# Namespace creation performs bucket and credential-provider RPCs. Keep those
# external calls out of the event loop and allow a normal burst of namespace
# requests without making the fourth request wait behind the first three.
_NAMESPACE_EXECUTOR = ThreadPoolExecutor(max_workers=16, thread_name_prefix='namespace-runtime')
_NAMESPACE_PROVISION_EXECUTOR = ThreadPoolExecutor(
    max_workers=32,
    thread_name_prefix='namespace-provision',
)
logger = logging.getLogger(__name__)


async def _run_namespace[**P, T](executor: Executor, function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, partial(function, *args, **kwargs))


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


def _create_namespace(name: str) -> NamespaceResponse:
    started = time.perf_counter()
    storage = _storage_response(name)

    # Registration is the publication fence: it is written only after the
    # bucket, credentials, and tenant schema are ready. Repeated picker
    # selections must therefore be a cheap idempotent read rather than
    # replaying all provisioning work under CI/browser load.
    if run_settings_db(runtime_namespace_exists, name):
        logger.info('Namespace already provisioned name=%s total_ms=%s', name, int((time.perf_counter() - started) * 1000))
        return NamespaceResponse(name=name, storage=storage, created_bucket=False)

    namespace_paths(name)

    # Bucket creation, credential provisioning, and tenant migration use
    # independent resources. Start all three together so a namespace request
    # is bounded by the slowest provisioning phase rather than the sum of
    # external object-store calls and Alembic startup. Registration remains
    # after all phases so a visible namespace is always usable.
    bucket_started = time.perf_counter()
    credentials_started = time.perf_counter()
    migration_started = time.perf_counter()
    bucket_future = _NAMESPACE_PROVISION_EXECUTOR.submit(_provision_namespace_bucket, name)
    credentials_future = _NAMESPACE_PROVISION_EXECUTOR.submit(
        run_settings_db,
        provision_namespace_engine_credentials,
        name,
    )
    migration_future = _NAMESPACE_PROVISION_EXECUTOR.submit(initialize_namespace_db, name)
    bucket_future.result()
    bucket_duration_ms = int((time.perf_counter() - bucket_started) * 1000)
    # Credentials before registration: a namespace that engines cannot open is
    # not usable, so a failure here must not leave one registered.
    # Use short-lived settings sessions for the DB phases. Bucket creation is
    # an external RPC and must not hold a database connection while it runs.
    credentials_future.result()
    credentials_duration_ms = int((time.perf_counter() - credentials_started) * 1000)
    migration_future.result()
    migration_duration_ms = int((time.perf_counter() - migration_started) * 1000)
    register_started = time.perf_counter()
    run_settings_db(register_namespace, name)
    register_duration_ms = int((time.perf_counter() - register_started) * 1000)
    logger.info(
        'Namespace provisioning completed name=%s total_ms=%s bucket_ms=%s credentials_ms=%s migration_ms=%s register_ms=%s',
        name,
        int((time.perf_counter() - started) * 1000),
        bucket_duration_ms,
        credentials_duration_ms,
        migration_duration_ms,
        register_duration_ms,
    )
    return NamespaceResponse(name=name, storage=storage, created_bucket=True)


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
async def create_namespace_endpoint(request: NamespaceCreateRequest) -> NamespaceResponse:
    """Register a namespace and create its S3 bucket (name == bucket)."""
    name = normalize_namespace(request.name)
    return await _run_namespace(_NAMESPACE_EXECUTOR, _create_namespace, name)
