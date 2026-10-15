from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend_core.config import settings
from backend_core.exceptions import SettingsConfigurationError

MASKED_SECRET = '••••••••'
_ENCRYPTED_PREFIX = 'enc:v1:'
_AAD = b'polars-fastapi-svelte.secret.v1'


@lru_cache(maxsize=8)
def _derive_key_for_material(material: str) -> bytes:
    return hashlib.sha256(material.encode('utf-8')).digest()


def _derive_key() -> bytes:
    material = os.getenv('SETTINGS_ENCRYPTION_KEY') or settings.settings_encryption_key
    if not material:
        raise SettingsConfigurationError('SETTINGS_ENCRYPTION_KEY must be set to encrypt stored secrets')
    return _derive_key_for_material(material)


def is_encrypted_secret(value: str | None) -> bool:
    return bool(value and value.startswith(_ENCRYPTED_PREFIX))


def is_masked_secret(value: str | None) -> bool:
    if not value:
        return False
    return value == MASKED_SECRET or set(value) == {'*'}


def mask_secret(value: str | None) -> str:
    return MASKED_SECRET if value else ''


def encrypt_secret(value: str) -> str:
    if not value:
        return ''
    aes = AESGCM(_derive_key())
    nonce = os.urandom(12)
    encrypted = aes.encrypt(nonce, value.encode('utf-8'), _AAD)
    payload = base64.urlsafe_b64encode(nonce + encrypted).decode('ascii')
    return f'{_ENCRYPTED_PREFIX}{payload}'


def decrypt_secret(value: str) -> str:
    if not value:
        return ''
    if not is_encrypted_secret(value):
        raise SettingsConfigurationError('Stored secret is not encrypted with the supported format')
    encoded = value.removeprefix(_ENCRYPTED_PREFIX)
    try:
        payload = base64.urlsafe_b64decode(f'{encoded}{"=" * (-len(encoded) % 4)}'.encode('ascii'))
    except ValueError as exc:
        raise SettingsConfigurationError('Stored secret could not be decrypted') from exc
    nonce, encrypted = payload[:12], payload[12:]
    if len(nonce) != 12 or not encrypted:
        raise SettingsConfigurationError('Stored secret uses an invalid encrypted format')
    aes = AESGCM(_derive_key())
    try:
        return aes.decrypt(nonce, encrypted, _AAD).decode('utf-8')
    except (InvalidTag, UnicodeDecodeError) as exc:
        raise SettingsConfigurationError('Stored secret could not be decrypted') from exc
