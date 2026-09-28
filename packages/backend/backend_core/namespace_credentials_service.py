from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets as crypto_secrets
import tempfile
import time
import uuid
from urllib.parse import urlparse

import aiohttp
from sqlmodel import Session, select

from backend_core.config import settings
from backend_core.database import namespace_provision_lock
from backend_core.persistence.namespaces.models import NamespaceEngineCredential
from backend_core.secrets import decrypt_secret, encrypt_secret

_ENGINE_CREDENTIAL_ROLES = ('reader', 'builder')
logger = logging.getLogger(__name__)


class NamespaceCredentialError(Exception):
    """Raised when namespace engine credentials cannot be provisioned or resolved."""


def _admin_client(session):
    from miniopy_async import MinioAdmin
    from miniopy_async.credentials import StaticProvider

    parsed = urlparse(settings.object_store_endpoint)
    if not parsed.hostname:
        raise NamespaceCredentialError(f'OBJECT_STORE_ENDPOINT is not a valid URL: {settings.object_store_endpoint}')
    netloc = parsed.netloc if parsed.port else parsed.hostname
    return MinioAdmin(
        netloc,
        StaticProvider(settings.object_store_access_key, settings.object_store_secret_key),
        region=settings.object_store_region,
        secure=parsed.scheme == 'https',
        session=session,
    )


async def _provision_roles(namespace: str, roles: list[str]) -> dict[str, tuple[str, str]]:
    """Create one object-store identity per role.

    The admin client never closes a session it opened itself, so the session is
    owned here and closed on the way out.
    """
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        admin = _admin_client(session)
        identities = await asyncio.gather(*(_create_role_identity(admin, namespace, role) for role in roles))
        return dict(zip(roles, identities, strict=True))


def _policy_document(namespace: str, role: str) -> dict:
    bucket = f'arn:aws:s3:::{namespace}'
    actions = ['s3:GetObject', 's3:ListBucket'] if role == 'reader' else ['s3:*']
    return {
        'Version': '2012-10-17',
        'Statement': [
            {'Effect': 'Allow', 'Action': actions, 'Resource': [bucket, f'{bucket}/*']},
        ],
    }


def _generate_access_key(namespace: str, role: str) -> str:
    return f'dfg-{namespace}-{role}-{crypto_secrets.token_hex(4)}'


async def _create_role_identity(admin, namespace: str, role: str) -> tuple[str, str]:
    started = time.perf_counter()
    access_key = _generate_access_key(namespace, role)
    secret_key = crypto_secrets.token_urlsafe(32)
    policy_name = f'namespace-{namespace}-{role}'
    # The admin client reads the policy from disk, and several API processes can
    # provision at once, so each call writes its own file.
    handle, policy_path = tempfile.mkstemp(prefix=f'{policy_name}-', suffix='.json')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as policy_file:
            json.dump(_policy_document(namespace, role), policy_file)
        user_started = time.perf_counter()
        await admin.user_add(access_key, secret_key)
        user_duration_ms = int((time.perf_counter() - user_started) * 1000)
        # add-canned-policy is a PUT: it creates or replaces, so re-running it
        # for an existing namespace role is how the policy stays current.
        policy_started = time.perf_counter()
        await admin.policy_add(policy_name, policy_path)
        policy_duration_ms = int((time.perf_counter() - policy_started) * 1000)
        policy_set_started = time.perf_counter()
        await admin.policy_set(policy_name, user=access_key)
        policy_set_duration_ms = int((time.perf_counter() - policy_set_started) * 1000)
        logger.info(
            'Namespace credential provisioning namespace=%s role=%s total_ms=%s user_ms=%s policy_add_ms=%s policy_set_ms=%s',
            namespace,
            role,
            int((time.perf_counter() - started) * 1000),
            user_duration_ms,
            policy_duration_ms,
            policy_set_duration_ms,
        )
    finally:
        os.remove(policy_path)
    return access_key, secret_key


def provision_namespace_engine_credentials(
    session: Session,
    namespace: str,
    *,
    namespace_lock_held: bool = False,
) -> None:
    """Create object-store identities for the namespace's engine roles.

    Idempotent: roles that already have records are left untouched. The
    namespace advisory lock serializes provisioning, while the DB session is
    released before object-store RPCs so slow network calls do not occupy a
    pooled connection or hold a transaction open.
    """
    if not namespace_lock_held and session.get_bind().dialect.name == 'postgresql':
        with namespace_provision_lock(namespace):
            _provision_namespace_engine_credentials(session, namespace)
        return
    _provision_namespace_engine_credentials(session, namespace)


def _provision_namespace_engine_credentials(session: Session, namespace: str) -> None:
    existing = session.exec(select(NamespaceEngineCredential).where(NamespaceEngineCredential.namespace == namespace)).all()
    existing_roles = {row.role for row in existing}
    missing_roles = [role for role in _ENGINE_CREDENTIAL_ROLES if role not in existing_roles]
    session.rollback()
    if not missing_roles:
        return

    try:
        identities = asyncio.run(_provision_roles(namespace, missing_roles))
    except Exception as exc:
        session.rollback()
        raise NamespaceCredentialError(f'Failed to provision engine credentials for namespace {namespace!r}') from exc
    for role, (access_key, secret_key) in identities.items():
        session.add(
            NamespaceEngineCredential(
                id=str(uuid.uuid4()),
                namespace=namespace,
                role=role,
                access_key=access_key,
                secret_key_encrypted=encrypt_secret(secret_key),
            )
        )
    session.commit()


def resolve_namespace_engine_credentials(session: Session, namespace: str, role: str) -> tuple[str, str]:
    """Return (access_key, secret_key) for the namespace and role.

    Raises NamespaceCredentialError when no record exists; never falls back to
    broader credentials.
    """
    row = session.exec(
        select(NamespaceEngineCredential).where(
            NamespaceEngineCredential.namespace == namespace,
            NamespaceEngineCredential.role == role,
        )
    ).first()
    if row is None:
        raise NamespaceCredentialError(f'No {role} credentials provisioned for namespace {namespace!r}')
    return row.access_key, decrypt_secret(row.secret_key_encrypted)
