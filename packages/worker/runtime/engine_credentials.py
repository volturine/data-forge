from __future__ import annotations

import json
from dataclasses import dataclass

from dataforge_protocol import compute_pb2, enums_pb2
from runtime.config import settings


@dataclass(frozen=True, slots=True)
class ObjectStoreCredentials:
    access_key: str
    secret_key: str
    session_token: str | None = None


def _credential_role(identity: compute_pb2.EngineIdentity) -> str:
    return "builder" if identity.scope == enums_pb2.ENGINE_SCOPE_BUILD else "reader"


def _configured_credentials(namespace: str, role: str) -> ObjectStoreCredentials | None:
    raw = settings.engine_object_store_credentials_json.strip()
    if not raw:
        return None
    try:
        document = json.loads(raw)
        values = document[namespace][role]
        access_key = values["access_key"]
        secret_key = values["secret_key"]
        session_token = values.get("session_token")
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Missing valid {role} object-store credentials for namespace {namespace!r}") from exc
    if not isinstance(access_key, str) or not access_key or not isinstance(secret_key, str) or not secret_key:
        raise RuntimeError(f"Missing valid {role} object-store credentials for namespace {namespace!r}")
    if session_token is not None and not isinstance(session_token, str):
        raise RuntimeError(f"Invalid session token for namespace {namespace!r}")
    return ObjectStoreCredentials(access_key=access_key, secret_key=secret_key, session_token=session_token)


def resolve_engine_credentials(namespace: str, identity: compute_pb2.EngineIdentity) -> ObjectStoreCredentials:
    """Resolve only namespace-scoped credentials for an engine launch."""
    credentials = _configured_credentials(namespace, _credential_role(identity))
    if credentials is None:
        if not settings.engine_allow_global_object_store_credentials or settings.prod_mode_enabled:
            raise RuntimeError(f"Namespace-scoped object-store credentials are required for engine namespace {namespace!r}")
        credentials = ObjectStoreCredentials(
            access_key=settings.object_store_access_key,
            secret_key=settings.object_store_secret_key,
        )
    if settings.prod_mode_enabled and (
        credentials.access_key == settings.object_store_access_key or credentials.secret_key == settings.object_store_secret_key
    ):
        raise RuntimeError("Production engine credentials must not reuse platform object-store credentials")
    return credentials
