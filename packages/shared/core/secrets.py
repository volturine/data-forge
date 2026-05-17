from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.config import settings
from core.exceptions import SettingsConfigurationError

MASKED_SECRET = '••••••••'
_ENCRYPTED_PREFIX = 'enc:v1:'
_AAD = b'polars-fastapi-svelte.secret.v1'


def _read_key_material() -> str:
    return os.getenv('SETTINGS_ENCRYPTION_KEY') or settings.settings_encryption_key


def encryption_available() -> bool:
    return bool(_read_key_material())


def _require_key_material() -> str:
    material = _read_key_material()
    if not material:
        raise SettingsConfigurationError('SETTINGS_ENCRYPTION_KEY must be set to encrypt stored secrets')
    return material


@lru_cache(maxsize=8)
def _derive_key_for_material(material: str) -> bytes:
    return hashlib.sha256(material.encode('utf-8')).digest()


def _derive_key() -> bytes:
    return _derive_key_for_material(_require_key_material())


def clear_key_cache() -> None:
    _derive_key_for_material.cache_clear()


def _decode_payload(payload: str) -> bytes:
    padding = '=' * (-len(payload) % 4)
    return base64.urlsafe_b64decode(f'{payload}{padding}'.encode('ascii'))


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
    if is_encrypted_secret(value):
        try:
            payload = _decode_payload(value.removeprefix(_ENCRYPTED_PREFIX))
            nonce = payload[:12]
            encrypted = payload[12:]
            if len(nonce) != 12 or not encrypted:
                raise SettingsConfigurationError('Stored secret uses an invalid encrypted format')
            aes = AESGCM(_derive_key())
            raw = aes.decrypt(nonce, encrypted, _AAD)
            return raw.decode('utf-8')
        except SettingsConfigurationError:
            raise
        except Exception as exc:
            raise SettingsConfigurationError('Stored secret could not be decrypted') from exc
    raise SettingsConfigurationError('Stored secret is not encrypted with the supported format')
