"""Secret-at-rest encryption: helpers, migration up/down, store reads."""

import datetime as dt
import uuid

import pytest
from alembic import command
from sqlmodel import Session

from backend_core.config import settings as app_settings
from backend_core.exceptions import SettingsConfigurationError
from backend_core.migrations import _alembic_config
from backend_core.persistence.telegram.models import TelegramSubscriber
from backend_core.secrets import (
    MASKED_SECRET,
    decrypt_secret,
    encrypt_secret,
    is_encrypted_secret,
    is_masked_secret,
    mask_secret,
)
from backend_core.telegram_schemas import ListenerCreate, SubscriberResponse
from backend_core.telegram_store import (
    _reveal_token,
    _store_token,
    add_listener,
    add_subscriber,
    get_notification_chat_ids,
    get_subscriber_by_chat,
    list_subscribers,
)

_PREVIOUS_TENANT_REVISION = '0002_runtime_tenant'


def _use_key(monkeypatch: pytest.MonkeyPatch, key: str | None) -> None:
    if key is None:
        monkeypatch.delenv('SETTINGS_ENCRYPTION_KEY', raising=False)
        monkeypatch.setattr(app_settings, 'settings_encryption_key', '', raising=False)
    else:
        monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', key)
        monkeypatch.setattr(app_settings, 'settings_encryption_key', key, raising=False)


# ---------------------------------------------------------------------------
# secrets.py roundtrip helpers
# ---------------------------------------------------------------------------


class TestSecretsRoundtrip:
    def test_roundtrip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_key(monkeypatch, 'test-key')
        encrypted = encrypt_secret('bot123:abc')
        assert encrypted != 'bot123:abc'
        assert is_encrypted_secret(encrypted)
        assert decrypt_secret(encrypted) == 'bot123:abc'

    def test_encrypt_is_non_deterministic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_key(monkeypatch, 'test-key')
        assert encrypt_secret('same') != encrypt_secret('same')

    def test_empty_value_stays_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_key(monkeypatch, 'test-key')
        assert encrypt_secret('') == ''
        assert decrypt_secret('') == ''

    def test_wrong_key_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_key(monkeypatch, 'first-key')
        encrypted = encrypt_secret('secret')
        _use_key(monkeypatch, 'second-key')
        with pytest.raises(SettingsConfigurationError):
            decrypt_secret(encrypted)

    def test_missing_key_rejects_encrypt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_key(monkeypatch, None)
        with pytest.raises(SettingsConfigurationError):
            encrypt_secret('secret')

    def test_mask_helpers(self) -> None:
        assert mask_secret('value') == MASKED_SECRET
        assert mask_secret('') == ''
        assert is_masked_secret(MASKED_SECRET)
        assert is_masked_secret('********')
        assert not is_masked_secret('real-token')


def test_subscriber_response_does_not_expose_token() -> None:
    response = SubscriberResponse.model_validate(
        TelegramSubscriber(
            id=1,
            chat_id='1',
            title='A',
            bot_token='tok',
            is_active=True,
            subscribed_at=dt.datetime.now(dt.UTC),
        ),
    )
    assert 'bot_token' not in SubscriberResponse.model_fields
    assert 'bot_token' not in response.model_dump()


# ---------------------------------------------------------------------------
# telegram_store encryption at rest
# ---------------------------------------------------------------------------


class TestTelegramStoreEncryptionAtRest:
    def test_add_subscriber_stores_token_encrypted(self, test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_key(monkeypatch, 'test-key')
        sub = add_subscriber(test_db_session, '111', 'Alice', 'tok-A')
        stored = test_db_session.get(TelegramSubscriber, sub.id)
        assert stored is not None
        assert stored.bot_token.startswith('enc:v1:')
        assert decrypt_secret(stored.bot_token) == 'tok-A'

    def test_empty_token_stays_empty(self, test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_key(monkeypatch, 'test-key')
        sub = add_subscriber(test_db_session, '112', 'Bob', '')
        stored = test_db_session.get(TelegramSubscriber, sub.id)
        assert stored is not None
        assert stored.bot_token == ''

    def test_reads_decrypt_transparently(self, test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_key(monkeypatch, 'test-key')
        sub = add_subscriber(test_db_session, '113', 'Carol', 'tok-B')
        add_listener(test_db_session, ListenerCreate(subscriber_id=sub.id, datasource_id='ds-enc'))
        test_db_session.expire_all()

        found = get_subscriber_by_chat(test_db_session, '113', 'tok-B')
        assert found is not None
        assert get_subscriber_by_chat(test_db_session, '113', 'other-token') is None

        matching = list_subscribers(test_db_session, bot_token='tok-B')
        assert [s.chat_id for s in matching] == ['113']
        assert list_subscribers(test_db_session, bot_token='other-token') == []

        assert get_notification_chat_ids(test_db_session, 'ds-enc') == [('113', 'tok-B')]

    def test_list_subscribers_without_filter(self, test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_key(monkeypatch, 'test-key')
        add_subscriber(test_db_session, '114', 'Dan', 'tok-C')
        assert len(list_subscribers(test_db_session)) == 1

    def test_missing_key_preserves_plaintext_behavior(self, test_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_key(monkeypatch, None)
        sub = add_subscriber(test_db_session, '115', 'Eve', 'plain-tok')
        stored = test_db_session.get(TelegramSubscriber, sub.id)
        assert stored is not None
        assert stored.bot_token == 'plain-tok'
        assert get_subscriber_by_chat(test_db_session, '115', 'plain-tok') is not None

    def test_store_and_reveal_helpers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_key(monkeypatch, 'test-key')
        assert _store_token('') == ''
        assert _store_token('tok').startswith('enc:v1:')
        assert _reveal_token(_store_token('tok')) == 'tok'
        assert _reveal_token('legacy-plaintext') == 'legacy-plaintext'
        assert _reveal_token('') == ''


# ---------------------------------------------------------------------------
# Migration backfill up/down on sample rows
# ---------------------------------------------------------------------------

_CREATE_APP_SETTINGS = """
CREATE TABLE app_settings (
    id INTEGER PRIMARY KEY,
    smtp_password VARCHAR NOT NULL DEFAULT '',
    telegram_bot_token VARCHAR NOT NULL DEFAULT '',
    openrouter_api_key VARCHAR NOT NULL DEFAULT '',
    openai_api_key VARCHAR NOT NULL DEFAULT ''
)
"""

_INSERT_APP_SETTINGS = """
INSERT INTO app_settings (id, smtp_password, telegram_bot_token, openrouter_api_key, openai_api_key)
VALUES (1, %(smtp)s, %(telegram)s, %(openrouter)s, %(openai)s)
"""

_INSERT_SUBSCRIBER = """
INSERT INTO telegram_subscribers (id, chat_id, title, bot_token, is_active, subscribed_at)
VALUES (%(id)s, %(chat_id)s, '', %(token)s, TRUE, NOW())
"""


def _run_alembic(postgres_container, schema: str, monkeypatch: pytest.MonkeyPatch, target: str, direction: str) -> None:
    monkeypatch.setattr(app_settings, 'database_url', postgres_container.url, raising=False)
    config = _alembic_config(scope='tenant', schema=schema)
    if direction == 'upgrade':
        command.upgrade(config, target)
    else:
        command.downgrade(config, target)


@pytest.fixture()
def tenant_schema_at_0002(postgres_container, monkeypatch: pytest.MonkeyPatch):
    schema = f'test_{uuid.uuid4().hex}'
    _run_alembic(postgres_container, schema, monkeypatch, _PREVIOUS_TENANT_REVISION, 'upgrade')
    with postgres_container.connect() as connection, connection.cursor() as cursor:
        cursor.execute(f'SET search_path TO "{schema}", public')
        cursor.execute(_CREATE_APP_SETTINGS)
        cursor.execute(_INSERT_SUBSCRIBER, {'id': 10, 'chat_id': 'chat-a', 'token': 'plaintext-bot-token'})
        cursor.execute(_INSERT_SUBSCRIBER, {'id': 11, 'chat_id': 'chat-b', 'token': ''})
        cursor.execute(_INSERT_SUBSCRIBER, {'id': 12, 'chat_id': 'chat-c', 'token': MASKED_SECRET})
        cursor.execute(
            _INSERT_APP_SETTINGS,
            {
                'smtp': 'smtp-secret',
                'telegram': 'tg-token',
                'openrouter': 'sk-or',
                'openai': MASKED_SECRET,
            },
        )
    try:
        yield schema
    finally:
        with postgres_container.connect() as cleanup, cleanup.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _fetch_secrets(postgres_container, schema: str) -> dict[str, str]:
    with postgres_container.connect() as connection, connection.cursor() as cursor:
        cursor.execute(f'SET search_path TO "{schema}", public')
        cursor.execute('SELECT smtp_password, telegram_bot_token, openrouter_api_key FROM app_settings WHERE id = 1')
        app_row = cursor.fetchone()
        cursor.execute('SELECT bot_token FROM telegram_subscribers WHERE id = 10')
        token_row = cursor.fetchone()
    return {
        'smtp_password': app_row[0],
        'telegram_bot_token': app_row[1],
        'openrouter_api_key': app_row[2],
        'bot_token': token_row[0],
    }


class TestEncryptSecretsMigration:
    def test_upgrade_encrypts_and_downgrade_restores(
        self,
        postgres_container,
        tenant_schema_at_0002: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _use_key(monkeypatch, 'migration-key')
        _run_alembic(postgres_container, tenant_schema_at_0002, monkeypatch, 'head', 'upgrade')

        values = _fetch_secrets(postgres_container, tenant_schema_at_0002)
        for name in ('smtp_password', 'telegram_bot_token', 'openrouter_api_key', 'bot_token'):
            assert values[name].startswith('enc:v1:')
        for name, plaintext in [
            ('smtp_password', 'smtp-secret'),
            ('telegram_bot_token', 'tg-token'),
            ('openrouter_api_key', 'sk-or'),
            ('bot_token', 'plaintext-bot-token'),
        ]:
            assert decrypt_secret(values[name]) == plaintext

        _run_alembic(postgres_container, tenant_schema_at_0002, monkeypatch, _PREVIOUS_TENANT_REVISION, 'downgrade')

        restored = _fetch_secrets(postgres_container, tenant_schema_at_0002)
        assert restored['smtp_password'] == 'smtp-secret'
        assert restored['telegram_bot_token'] == 'tg-token'
        assert restored['openrouter_api_key'] == 'sk-or'
        assert restored['bot_token'] == 'plaintext-bot-token'

    def test_upgrade_skips_masked_and_empty_values(
        self,
        postgres_container,
        tenant_schema_at_0002: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _use_key(monkeypatch, 'migration-key')
        _run_alembic(postgres_container, tenant_schema_at_0002, monkeypatch, 'head', 'upgrade')

        with postgres_container.connect() as connection, connection.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{tenant_schema_at_0002}", public')
            cursor.execute('SELECT openai_api_key FROM app_settings WHERE id = 1')
            assert cursor.fetchone()[0] == MASKED_SECRET
            cursor.execute('SELECT bot_token FROM telegram_subscribers WHERE id IN (11, 12)')
            assert cursor.fetchall() == [('',), (MASKED_SECRET,)]

    def test_upgrade_is_idempotent_for_already_encrypted_values(
        self,
        postgres_container,
        tenant_schema_at_0002: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _use_key(monkeypatch, 'migration-key')
        pre_encrypted = encrypt_secret('already-encrypted-token')
        with postgres_container.connect() as connection, connection.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{tenant_schema_at_0002}", public')
            cursor.execute('UPDATE telegram_subscribers SET bot_token = %s WHERE id = 12', (pre_encrypted,))

        _run_alembic(postgres_container, tenant_schema_at_0002, monkeypatch, 'head', 'upgrade')

        with postgres_container.connect() as connection, connection.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{tenant_schema_at_0002}", public')
            cursor.execute('SELECT bot_token FROM telegram_subscribers WHERE id = 12')
            assert cursor.fetchone()[0] == pre_encrypted

    def test_upgrade_without_key_leaves_plaintext(
        self,
        postgres_container,
        tenant_schema_at_0002: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _use_key(monkeypatch, None)
        _run_alembic(postgres_container, tenant_schema_at_0002, monkeypatch, 'head', 'upgrade')

        values = _fetch_secrets(postgres_container, tenant_schema_at_0002)
        assert values['smtp_password'] == 'smtp-secret'
        assert values['telegram_bot_token'] == 'tg-token'
        assert values['openrouter_api_key'] == 'sk-or'
        assert values['bot_token'] == 'plaintext-bot-token'
