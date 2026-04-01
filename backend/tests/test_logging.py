from core.logging import redact_logged_body


class TestLoggingRedaction:
    def test_redacts_settings_request_secret_fields(self) -> None:
        body = '{"smtp_password":"pw","telegram_bot_token":"bot","openrouter_api_key":"sk"}'
        redacted = redact_logged_body('/api/v1/settings', body)
        assert redacted == '{"smtp_password": "[REDACTED]", "telegram_bot_token": "[REDACTED]", "openrouter_api_key": "[REDACTED]"}'

    def test_redacts_chat_and_auth_secret_fields(self) -> None:
        body = '{"api_key":"sk-test","password":"pw","current_password":"old","new_password":"new"}'
        redacted = redact_logged_body('/api/v1/ai/chat/sessions', body)
        assert '[REDACTED]' in str(redacted)
        assert 'sk-test' not in str(redacted)
        assert '"password": "[REDACTED]"' in str(redacted)

    def test_leaves_non_sensitive_paths_unchanged(self) -> None:
        body = '{"api_key":"sk-test","value":1}'
        assert redact_logged_body('/api/v1/config', body) == body
