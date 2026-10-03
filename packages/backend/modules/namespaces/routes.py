import logging
import time
from collections.abc import Callable
from concurrent.futures import Future
from functools import partial

from fastapi import Depends, Query
from pydantic import BaseModel, Field

from backend_core.api_execution_budget import BoundedThreadPoolExecutor, run_api_blocking, run_in_bounded_executor
from backend_core.data_plane_client import client_from_settings
from backend_core.database import initialize_namespace_db, namespace_provision_lock, run_settings_db
from backend_core.error_handlers import handle_errors
from backend_core.namespace import list_namespaces, namespace_paths, normalize_namespace
from backend_core.namespace_credentials_service import provision_namespace_engine_credentials
from backend_core.namespace_storage import NAMESPACE_NAME_RULES, namespace_storage_plan
from backend_core.namespaces_service import list_runtime_namespaces, register_namespace, runtime_namespace_exists
from modules.auth.dependencies import get_current_user
from modules.mcp.router import MCPRouter

router = MCPRouter(prefix='/namespaces', tags=['namespaces'])
# Namespace creation performs bucket and credential-provider RPCs. Keep those
# external calls out of the event loop, but do not turn a browser burst into
# dozens of DB sessions and object-store admin calls.
_NAMESPACE_EXECUTOR = BoundedThreadPoolExecutor(
    max_workers=2,
    max_pending=2,
    thread_name_prefix='namespace-runtime',
)
_NAMESPACE_PROVISION_EXECUTOR = BoundedThreadPoolExecutor(
    max_workers=3,
    # At most two namespace jobs run concurrently; each can submit one bucket,
    # credentials, and migration task, so six outstanding operations suffice.
    max_pending=3,
    thread_name_prefix='namespace-provision',
)
logger = logging.getLogger(__name__)


async def _run_namespace[**P, T](executor: BoundedThreadPoolExecutor, function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    return await run_in_bounded_executor(executor, work=partial(function, *args, **kwargs))


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
    # This session-level PostgreSQL lock covers the publication check and every
    # provisioning side effect, including calls from other API processes.
    lock_started = time.perf_counter()
    with namespace_provision_lock(name):
        lock_wait_ms = int((time.perf_counter() - lock_started) * 1000)
        if lock_wait_ms >= 1000:
            logger.warning('Namespace provisioning lock waited name=%s wait_ms=%s', name, lock_wait_ms)
        return _create_namespace_locked(name)


def _wait_for_namespace_work(futures: list[Future]) -> list[BaseException]:
    failures: list[BaseException] = []
    for future in futures:
        try:
            future.result()
        except BaseException as exc:
            failures.append(exc)
    return failures


def _create_namespace_locked(name: str) -> NamespaceResponse:
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
    phase_durations: dict[str, int] = {}

    def run_phase(phase: str, function: Callable[..., object], *args: object) -> object:
        phase_started = time.perf_counter()
        try:
            return function(*args)
        finally:
            phase_durations[phase] = int((time.perf_counter() - phase_started) * 1000)

    futures: list[Future] = []
    try:
        futures.append(_NAMESPACE_PROVISION_EXECUTOR.submit(run_phase, 'bucket', _provision_namespace_bucket, name))
        futures.append(
            _NAMESPACE_PROVISION_EXECUTOR.submit(
                run_phase,
                'credentials',
                partial(
                    run_settings_db,
                    provision_namespace_engine_credentials,
                    name,
                    namespace_lock_held=True,
                ),
            )
        )
        futures.append(_NAMESPACE_PROVISION_EXECUTOR.submit(run_phase, 'migration', initialize_namespace_db, name))
    except BaseException:
        _wait_for_namespace_work(futures)
        raise

    failures = _wait_for_namespace_work(futures)
    if failures:
        raise failures[0]

    # Credentials before registration: a namespace that engines cannot open is
    # not usable, so a failure here must not leave one registered.
    # Use short-lived settings sessions for the DB phases. Bucket creation is
    # an external RPC and must not hold a database connection while it runs.
    bucket_duration_ms = phase_durations['bucket']
    credentials_duration_ms = phase_durations['credentials']
    migration_duration_ms = phase_durations['migration']
    register_started = time.perf_counter()
    run_settings_db(register_namespace, name)
    register_duration_ms = int((time.perf_counter() - register_started) * 1000)
    total_duration_ms = int((time.perf_counter() - started) * 1000)
    log_provisioning = logger.warning if total_duration_ms >= 5_000 else logger.info
    log_provisioning(
        'Namespace provisioning completed name=%s total_ms=%s bucket_ms=%s credentials_ms=%s migration_ms=%s register_ms=%s',
        name,
        total_duration_ms,
        bucket_duration_ms,
        credentials_duration_ms,
        migration_duration_ms,
        register_duration_ms,
    )
    return NamespaceResponse(name=name, storage=storage, created_bucket=True)


@router.get('', response_model=NamespaceListResponse, mcp=True)
@handle_errors(operation='list namespaces')
async def list_namespaces_endpoint() -> NamespaceListResponse:
    """List namespaces. Each name is an S3 bucket."""

    def load_names() -> list[str]:
        names = {*list_namespaces(), *run_settings_db(list_runtime_namespaces)}
        return sorted(names)

    return NamespaceListResponse(namespaces=await run_api_blocking(load_names))


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
