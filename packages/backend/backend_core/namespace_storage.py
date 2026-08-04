"""Namespace is the S3 bucket. That is the entire mapping."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Same rules as packages/worker/runtime/object_store.py — keep in lockstep.
_NAMESPACE_BUCKET_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{1,61}[a-z0-9]$')

NAMESPACE_NAME_RULES = (
    '3–63 characters; lowercase letters, digits, hyphens, and underscores; '
    'must start and end with a letter or digit. '
    'The name is the S3 bucket — nothing is rewritten.'
)


def is_valid_namespace_name(name: str) -> bool:
    if not name or len(name) < 3 or len(name) > 63:
        return False
    if '..' in name or name.startswith('xn--'):
        return False
    return _NAMESPACE_BUCKET_RE.match(name) is not None


def validate_namespace_name(name: str) -> str:
    raw = name.strip()
    if not is_valid_namespace_name(raw):
        raise ValueError(f'Invalid namespace {name!r}. {NAMESPACE_NAME_RULES}')
    return raw


@dataclass(frozen=True, slots=True)
class NamespaceStoragePlan:
    """Concrete storage roots for a namespace bucket."""

    name: str
    bucket: str
    uploads_root: str
    clean_root: str
    exports_root: str
    runtime_artifacts_root: str

    def as_dict(self) -> dict[str, str]:
        return {
            'name': self.name,
            'bucket': self.bucket,
            'uploads_root': self.uploads_root,
            'clean_root': self.clean_root,
            'exports_root': self.exports_root,
            'runtime_artifacts_root': self.runtime_artifacts_root,
        }


def namespace_storage_plan(namespace: str) -> NamespaceStoragePlan:
    name = validate_namespace_name(namespace)

    def root(*parts: str) -> str:
        key = '/'.join(part.strip('/') for part in parts if part.strip('/'))
        return f's3://{name}/{key}'

    return NamespaceStoragePlan(
        name=name,
        bucket=name,
        uploads_root=root('uploads'),
        clean_root=root('clean'),
        exports_root=root('exports'),
        runtime_artifacts_root=root('runtime-artifacts'),
    )
