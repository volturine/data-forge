from __future__ import annotations

import threading
from concurrent.futures import Future
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
_inflight: dict[tuple[str, str], Future[ObjectStoreCredentials]] = {}
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
    key = (namespace, role)
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None:
            return cached
        flight = _inflight.get(key)
        if flight is None:
            flight = Future()
            _inflight[key] = flight
            owns_flight = True
        else:
            owns_flight = False

    if not owns_flight:
        return flight.result()

    try:
        response = client_from_env().engine_credentials(namespace=namespace, role=role)
        credentials = ObjectStoreCredentials(access_key=response.access_key, secret_key=response.secret_key)
    except BaseException as exc:
        with _cache_lock:
            _inflight.pop(key, None)
        flight.set_exception(exc)
        raise

    with _cache_lock:
        _cache[key] = credentials
        _inflight.pop(key, None)
    flight.set_result(credentials)
    return credentials
