from __future__ import annotations

from dataclasses import dataclass

from dataforge_protocol import compute_pb2, enums_pb2
from runtime.worker_runtime_client import client_from_env


@dataclass(frozen=True, slots=True)
class ObjectStoreCredentials:
    access_key: str
    secret_key: str
    session_token: str | None = None


def _credential_role(identity: compute_pb2.EngineIdentity) -> str:
    return "builder" if identity.scope == enums_pb2.ENGINE_SCOPE_BUILD else "reader"


def resolve_engine_credentials(namespace: str, identity: compute_pb2.EngineIdentity) -> ObjectStoreCredentials:
    """Fetch namespace-scoped engine credentials from the backend.

    The backend provisions one reader and one builder identity per namespace
    and hands out only the role matching the engine scope. A missing record
    fails the launch; there is no broader-credential fallback.
    """
    response = client_from_env().engine_credentials(namespace=namespace, role=_credential_role(identity))
    return ObjectStoreCredentials(access_key=response.access_key, secret_key=response.secret_key)
