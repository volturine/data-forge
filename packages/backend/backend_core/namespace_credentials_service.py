from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets as crypto_secrets
import uuid
from urllib.parse import urlparse

from sqlmodel import Session, select

from backend_core.config import settings
from backend_core.persistence.namespaces.models import NamespaceEngineCredential
from backend_core.secrets import decrypt_secret, encrypt_secret

_ENGINE_CREDENTIAL_ROLES = ('reader', 'builder')


class NamespaceCredentialError(Exception):
    """Raised when namespace engine credentials cannot be provisioned or resolved."""


def _admin_client():
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
    )


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
    access_key = _generate_access_key(namespace, role)
    secret_key = crypto_secrets.token_urlsafe(32)
    policy_name = f'namespace-{namespace}-{role}'
    policy_path = f'/tmp/{policy_name}.json'
    try:
        with open(policy_path, 'w', encoding='utf-8') as policy_file:
            json.dump(_policy_document(namespace, role), policy_file)
        await admin.user_add(access_key, secret_key)
        with contextlib.suppress(Exception):
            # The policy document is deterministic per namespace and role;
            # reuse the existing one when it was provisioned before.
            await admin.policy_add(policy_name, policy_path)
        await admin.policy_set(policy_name, user=access_key)
    finally:
        os.remove(policy_path)
    return access_key, secret_key


def provision_namespace_engine_credentials(session: Session, namespace: str) -> None:
    """Create object-store identities for the namespace's engine roles.

    Idempotent: roles that already have active records are left untouched.
    """
    existing = session.exec(select(NamespaceEngineCredential).where(NamespaceEngineCredential.namespace == namespace)).all()
    existing_roles = {row.role for row in existing}
    missing_roles = [role for role in _ENGINE_CREDENTIAL_ROLES if role not in existing_roles]
    if not missing_roles:
        return

    admin = _admin_client()

    async def provision_all():
        return {role: await _create_role_identity(admin, namespace, role) for role in missing_roles}

    try:
        identities = asyncio.run(provision_all())
    except Exception as exc:
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


def engine_object_store_config() -> dict[str, str]:
    """Endpoint and region metadata returned alongside engine credentials."""
    return {
        'endpoint': settings.object_store_endpoint,
        'region': settings.object_store_region,
    }
