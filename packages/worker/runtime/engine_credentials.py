from __future__ import annotations

import threading
from dataclasses import dataclass

from dataforge_protocol import compute_pb2, enums_pb2
from runtime.worker_runtime_client import client_from_env


@dataclass(frozen=True, slots=True)
class ObjectStoreCredentials:
    access_key: str
    secret_key: str
    session_token: str | None = None


# Engine launches are latency-critical and every launch needs the namespace's
# credential. The backend provisions each namespace role once and never
# rewrites it, so the resolved identity is cached for the worker's lifetime.
_cache: dict[tuple[str, str], ObjectStoreCredentials] = {}
_cache_lock = threading.Lock()


def _credential_role(identity: compute_pb2.EngineIdentity) -> str:
    return "builder" if identity.scope == enums_pb2.ENGINE_SCOPE_BUILD else "reader"


def resolve_engine_credentials(namespace: str, identity: compute_pb2.EngineIdentity) -> ObjectStoreCredentials:
    """Fetch namespace-scoped engine credentials from the backend.

    The backend provisions one reader and one builder identity per namespace
    and hands out only the role matching the engine scope. A missing record
    fails the launch; there is no broader-credential fallback.
    """
    role = _credential_role(identity)
    with _cache_lock:
        cached = _cache.get((namespace, role))
    if cached is not None:
        return cached
    response = client_from_env().engine_credentials(namespace=namespace, role=role)
    credentials = ObjectStoreCredentials(access_key=response.access_key, secret_key=response.secret_key)
    with _cache_lock:
        _cache[(namespace, role)] = credentials
    return credentials
