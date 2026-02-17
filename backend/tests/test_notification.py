from dataclasses import dataclass
from unittest.mock import patch

import polars as pl
import pytest
from pydantic import ValidationError

from core.exceptions import PipelineExecutionError
from modules.compute.operations.notification import (
    NotificationHandler,
    NotificationParams,
    _build_message,
)
from modules.compute.service import _send_pipeline_notifications
from modules.compute.step_converter import convert_notification_config
from modules.notification.service import render_template


@dataclass(frozen=True)
class MockSubscriber:
    chat_id: str
    bot_token: str
    is_active: bool = True


class TestNotificationParams:
    def test_basic(self):
        params = NotificationParams.model_validate(
            {
                'method': 'email',
                'recipient': 'user@example.com',
                'input_columns': ['body'],
            }
        )
        assert params.method == 'email'
        assert params.recipient == 'user@example.com'
        assert params.input_columns == ['body']
        assert params.output_column == 'notification_status'
        assert params.message_template == '{{message}}'
        assert params.subject_template == 'Notification'
        assert params.batch_size == 10
        assert params.timeout_seconds == 20

    def test_telegram_method(self):
        params = NotificationParams.model_validate(
            {
                'method': 'telegram',
                'recipient': '12345',
                'input_columns': ['col'],
            }
        )
        assert params.method == 'telegram'

    def test_invalid_method_rejected(self):
        with pytest.raises(ValidationError):
            NotificationParams.model_validate(
                {
                    'method': 'slack',
                    'recipient': 'test',
                    'input_columns': ['col'],
                }
            )

    def test_empty_recipient_rejected(self):
        with pytest.raises(ValidationError, match='recipient'):
            NotificationParams.model_validate(
                {
                    'method': 'email',
                    'recipient': '',
                    'input_columns': ['col'],
                }
            )

    def test_missing_recipient_rejected(self):
        with pytest.raises(ValidationError, match='recipient'):
            NotificationParams.model_validate(
                {
                    'method': 'email',
                    'input_columns': ['col'],
                }
            )

    def test_recipient_column_allows_missing_recipient(self):
        params = NotificationParams.model_validate(
            {
                'method': 'telegram',
                'recipient_column': 'chat_id',
                'input_columns': ['body'],
            }
        )
        assert params.recipient_column == 'chat_id'

    def test_empty_input_columns_rejected(self):
        with pytest.raises(ValidationError, match='input_columns'):
            NotificationParams.model_validate(
                {
                    'method': 'email',
                    'recipient': 'test@test.com',
                    'input_columns': [],
                }
            )

    def test_no_input_columns_rejected(self):
        with pytest.raises(ValidationError, match='input_columns'):
            NotificationParams.model_validate(
                {
                    'method': 'email',
                    'recipient': 'test@test.com',
                }
            )

    def test_multi_columns(self):
        params = NotificationParams.model_validate(
            {
                'method': 'email',
                'recipient': 'test@test.com',
                'input_columns': ['title', 'body', 'status'],
            }
        )
        assert params.input_columns == ['title', 'body', 'status']

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            NotificationParams.model_validate(
                {
                    'method': 'email',
                    'recipient': 'test@test.com',
                    'input_columns': ['col'],
                    'unknown_field': True,
                }
            )

    def test_custom_batch_size(self):
        params = NotificationParams.model_validate(
            {
                'method': 'email',
                'recipient': 'test@test.com',
                'input_columns': ['col'],
                'batch_size': 50,
            }
        )
        assert params.batch_size == 50

    def test_bot_token_default_empty(self):
        params = NotificationParams.model_validate(
            {
                'method': 'telegram',
                'recipient': '123',
                'input_columns': ['col'],
            }
        )
        assert params.bot_token == ''

    def test_bot_token_custom(self):
        params = NotificationParams.model_validate(
            {
                'method': 'telegram',
                'recipient': '123',
                'input_columns': ['col'],
                'bot_token': '123456:ABC-DEF',
            }
        )
        assert params.bot_token == '123456:ABC-DEF'


class TestBuildMessage:
    def test_single_placeholder(self):
        assert _build_message('Hello {{name}}!', {'name': 'Alice'}) == 'Hello Alice!'

    def test_multiple_placeholders(self):
        result = _build_message('{{title}}: {{body}}', {'title': 'Alert', 'body': 'Fire'})
        assert result == 'Alert: Fire'

    def test_missing_key_untouched(self):
        result = _build_message('Hello {{name}}!', {})
        assert result == 'Hello {{name}}!'

    def test_numeric_value(self):
        result = _build_message('Count: {{n}}', {'n': 42})
        assert result == 'Count: 42'

    def test_no_placeholders(self):
        result = _build_message('Plain text', {'key': 'val'})
        assert result == 'Plain text'


class TestNotificationHandler:
    def test_email_per_row(self):
        """Each row triggers one email send; status column added."""
        handler = NotificationHandler()
        lf = pl.DataFrame({'body': ['hello', 'world', 'test']}).lazy()

        with patch('modules.compute.operations.notification.notification_service') as mock_svc:
            result = handler(
                lf,
                {
                    'method': 'email',
                    'recipient': 'dest@test.com',
                    'input_columns': ['body'],
                    'output_column': 'send_status',
                    'message_template': 'Msg: {{body}}',
                    'subject_template': 'Subj: {{body}}',
                },
            )
            collected = result.collect()
        assert 'send_status' in collected.columns
        assert collected['send_status'].to_list() == ['sent', 'sent', 'sent']
        assert mock_svc.send_email.call_count == 3

        first_call = mock_svc.send_email.call_args_list[0]
        assert first_call.kwargs['to'] == 'dest@test.com'
        assert first_call.kwargs['subject'] == 'Subj: hello'
        assert first_call.kwargs['body'] == 'Msg: hello'

    def test_lazy_execution_defers_side_effects(self):
        handler = NotificationHandler()
        lf = pl.DataFrame({'body': ['hello']}).lazy()

        with patch('modules.compute.operations.notification.notification_service') as mock_svc:
            result = handler(
                lf,
                {
                    'method': 'email',
                    'recipient': 'dest@test.com',
                    'input_columns': ['body'],
                    'output_column': 'send_status',
                    'message_template': 'Msg: {{body}}',
                    'subject_template': 'Subj: {{body}}',
                },
            )
            mock_svc.send_email.assert_not_called()
            result.collect()
            mock_svc.send_email.assert_called_once()

    def test_telegram_per_row(self):
        handler = NotificationHandler()
        lf = pl.DataFrame({'msg': ['hi']}).lazy()

        with (
            patch('modules.compute.operations.notification.notification_service') as mock_svc,
            patch('modules.compute.operations.notification.get_resolved_telegram_settings') as mock_settings,
        ):
            mock_settings.return_value = {'enabled': True, 'token': 'tok'}
            result = handler(
                lf,
                {
                    'method': 'telegram',
                    'recipient': '99999',
                    'input_columns': ['msg'],
                    'message_template': '{{msg}}',
                },
            )
            collected = result.collect()
        assert collected['notification_status'].to_list() == ['sent']
        mock_svc.send_telegram.assert_called_once_with(chat_id='99999', message='hi')

    def test_multi_column_template(self):
        handler = NotificationHandler()
        lf = pl.DataFrame(
            {
                'name': ['Alice', 'Bob'],
                'amount': [100, 200],
            }
        ).lazy()

        with patch('modules.compute.operations.notification.notification_service') as mock_svc:
            result = handler(
                lf,
                {
                    'method': 'email',
                    'recipient': 'x@x.com',
                    'input_columns': ['name', 'amount'],
                    'message_template': '{{name}} owes {{amount}}',
                    'subject_template': 'Invoice for {{name}}',
                },
            )
            collected = result.collect()
        assert collected.height == 2
        second_call = mock_svc.send_email.call_args_list[1]
        assert second_call.kwargs['body'] == 'Bob owes 200'
        assert second_call.kwargs['subject'] == 'Invoice for Bob'

    def test_error_handling_per_row(self):
        handler = NotificationHandler()
        lf = pl.DataFrame({'col': ['ok', 'bad', 'ok2']}).lazy()

        with patch('modules.compute.operations.notification.notification_service') as mock_svc:
            mock_svc.send_email.side_effect = [None, RuntimeError('SMTP down'), None]
            result = handler(
                lf,
                {
                    'method': 'email',
                    'recipient': 'x@x.com',
                    'input_columns': ['col'],
                    'message_template': '{{col}}',
                },
            )
            collected = result.collect()
        statuses = collected['notification_status'].to_list()
        assert statuses[0] == 'sent'
        assert statuses[1].startswith('[error:')
        assert 'SMTP down' in statuses[1]
        assert statuses[2] == 'sent'

    def test_empty_dataframe(self):
        handler = NotificationHandler()
        lf = pl.DataFrame({'col': []}).cast({'col': pl.Utf8}).lazy()

        with patch('modules.compute.operations.notification.notification_service') as mock_svc:
            result = handler(
                lf,
                {
                    'method': 'email',
                    'recipient': 'x@x.com',
                    'input_columns': ['col'],
                    'message_template': '{{col}}',
                },
            )
            collected = result.collect()
        assert collected.height == 0
        assert 'notification_status' in collected.columns
        mock_svc.send_email.assert_not_called()

    def test_missing_column_raises(self):
        handler = NotificationHandler()
        lf = pl.DataFrame({'a': [1]}).lazy()

        with pytest.raises(ValueError, match='not found'):
            handler(
                lf,
                {
                    'method': 'email',
                    'recipient': 'x@x.com',
                    'input_columns': ['nonexistent'],
                    'message_template': '{{nonexistent}}',
                },
            )

    def test_batch_size_respected(self):
        """Batching works correctly — all rows processed."""
        handler = NotificationHandler()
        lf = pl.DataFrame({'v': list(range(25))}).lazy()

        with patch('modules.compute.operations.notification.notification_service') as mock_svc:
            result = handler(
                lf,
                {
                    'method': 'email',
                    'recipient': 'x@x.com',
                    'input_columns': ['v'],
                    'message_template': '{{v}}',
                    'batch_size': 7,
                },
            )
            collected = result.collect()
        assert collected.height == 25
        assert mock_svc.send_email.call_count == 25
        assert all(s == 'sent' for s in collected['notification_status'].to_list())

    def test_preserves_original_columns(self):
        handler = NotificationHandler()
        lf = pl.DataFrame({'a': [1, 2], 'b': ['x', 'y']}).lazy()

        with patch('modules.compute.operations.notification.notification_service'):
            result = handler(
                lf,
                {
                    'method': 'email',
                    'recipient': 'x@x.com',
                    'input_columns': ['b'],
                    'message_template': '{{b}}',
                    'output_column': 'status',
                },
            )
            collected = result.collect()
        assert collected.columns == ['a', 'b', 'status']
        assert collected['a'].to_list() == [1, 2]
        assert collected['b'].to_list() == ['x', 'y']

    def test_telegram_comma_separated_recipients(self):
        handler = NotificationHandler()
        lf = pl.DataFrame({'msg': ['hello']}).lazy()

        with (
            patch('modules.compute.operations.notification.notification_service') as mock_svc,
            patch('modules.compute.operations.notification.get_resolved_telegram_settings') as mock_settings,
        ):
            mock_settings.return_value = {'enabled': True, 'token': 'tok'}
            result = handler(
                lf,
                {
                    'method': 'telegram',
                    'recipient': '111, 222, 333',
                    'input_columns': ['msg'],
                    'message_template': '{{msg}}',
                },
            )
            collected = result.collect()
        assert collected['notification_status'].to_list() == ['sent']
        assert mock_svc.send_telegram.call_count == 3
        called_ids = [c.kwargs['chat_id'] for c in mock_svc.send_telegram.call_args_list]
        assert called_ids == ['111', '222', '333']

    def test_recipient_column_override(self):
        handler = NotificationHandler()
        lf = pl.DataFrame({'msg': ['hi'], 'chat_id': ['888']}).lazy()

        with (
            patch('modules.compute.operations.notification.notification_service') as mock_svc,
            patch('modules.compute.operations.notification.get_resolved_telegram_settings') as mock_settings,
        ):
            mock_settings.return_value = {'enabled': True, 'token': 'tok'}
            result = handler(
                lf,
                {
                    'method': 'telegram',
                    'recipient': '999',
                    'recipient_column': 'chat_id',
                    'input_columns': ['msg'],
                    'message_template': '{{msg}}',
                },
            )
            collected = result.collect()

        assert collected['notification_status'].to_list() == ['sent']
        mock_svc.send_telegram.assert_called_once_with(chat_id='888', message='hi')

    def test_recipient_column_array(self):
        handler = NotificationHandler()
        lf = pl.DataFrame({'msg': ['hi'], 'chat_ids': [['111', '222']]}).lazy()

        with (
            patch('modules.compute.operations.notification.notification_service') as mock_svc,
            patch('modules.compute.operations.notification.get_resolved_telegram_settings') as mock_settings,
        ):
            mock_settings.return_value = {'enabled': True, 'token': 'tok'}
            result = handler(
                lf,
                {
                    'method': 'telegram',
                    'recipient_column': 'chat_ids',
                    'input_columns': ['msg'],
                    'message_template': '{{msg}}',
                },
            )
            collected = result.collect()

        assert collected['notification_status'].to_list() == ['sent']
        assert mock_svc.send_telegram.call_count == 2
        called_ids = [c.kwargs['chat_id'] for c in mock_svc.send_telegram.call_args_list]
        assert called_ids == ['111', '222']

    def test_telegram_custom_bot_token(self):
        handler = NotificationHandler()
        lf = pl.DataFrame({'msg': ['hi']}).lazy()

        with (
            patch('modules.compute.operations.notification.httpx') as mock_httpx,
            patch('modules.compute.operations.notification.notification_service') as mock_svc,
            patch('modules.compute.operations.notification.get_resolved_telegram_settings') as mock_settings,
        ):
            mock_settings.return_value = {'enabled': True, 'token': 'tok'}
            result = handler(
                lf,
                {
                    'method': 'telegram',
                    'recipient': '12345',
                    'input_columns': ['msg'],
                    'message_template': '{{msg}}',
                    'bot_token': 'custom-token-123',
                },
            )
            collected = result.collect()
        assert collected['notification_status'].to_list() == ['sent']
        mock_svc.send_telegram.assert_not_called()
        mock_httpx.post.assert_called_once()
        call_args = mock_httpx.post.call_args
        assert 'custom-token-123' in call_args.args[0]
        assert call_args.kwargs['json']['chat_id'] == '12345'

    def test_telegram_custom_bot_multi_recipients(self):
        handler = NotificationHandler()
        lf = pl.DataFrame({'msg': ['test']}).lazy()

        with (
            patch('modules.compute.operations.notification.httpx') as mock_httpx,
            patch('modules.compute.operations.notification.notification_service') as mock_svc,
            patch('modules.compute.operations.notification.get_resolved_telegram_settings') as mock_settings,
        ):
            mock_settings.return_value = {'enabled': True, 'token': 'tok'}
            result = handler(
                lf,
                {
                    'method': 'telegram',
                    'recipient': 'aaa, bbb',
                    'input_columns': ['msg'],
                    'message_template': '{{msg}}',
                    'bot_token': 'tok123',
                },
            )
            collected = result.collect()
        assert collected['notification_status'].to_list() == ['sent']
        mock_svc.send_telegram.assert_not_called()
        assert mock_httpx.post.call_count == 2
        sent_ids = [c.kwargs['json']['chat_id'] for c in mock_httpx.post.call_args_list]
        assert sent_ids == ['aaa', 'bbb']


class TestConvertNotificationConfig:
    def test_basic(self):
        result = convert_notification_config(
            {
                'method': 'telegram',
                'recipient': '12345',
                'input_columns': ['col1', 'col2'],
                'output_column': 'status',
                'message_template': '{{col1}} — {{col2}}',
            }
        )
        assert result['method'] == 'telegram'
        assert result['recipient'] == '12345'
        assert result['input_columns'] == ['col1', 'col2']
        assert result['output_column'] == 'status'

    def test_defaults(self):
        result = convert_notification_config({})
        assert result['method'] == 'email'
        assert result['recipient'] == ''
        assert result['subscriber_ids'] == []
        assert result['input_columns'] == []
        assert result['output_column'] == 'notification_status'
        assert result['message_template'] == '{{message}}'
        assert result['subject_template'] == 'Notification'
        assert result['batch_size'] == 10

    def test_subscriber_ids_fallback(self):
        result = convert_notification_config({'subscriber_ids': ['111', '222']})
        assert result['recipient'] == '111,222'
        assert result['subscriber_ids'] == ['111', '222']

    def test_camelCase_support(self):
        result = convert_notification_config(
            {
                'inputColumns': ['a', 'b'],
                'outputColumn': 'stat',
                'messageTemplate': 'tpl',
                'subjectTemplate': 'sub',
            }
        )
        assert result['input_columns'] == ['a', 'b']
        assert result['output_column'] == 'stat'
        assert result['message_template'] == 'tpl'
        assert result['subject_template'] == 'sub'

    def test_recipient_column_passthrough(self):
        result = convert_notification_config({'recipient_column': 'chat'})
        assert result['recipient_column'] == 'chat'

    def test_bot_token_passthrough(self):
        result = convert_notification_config(
            {
                'method': 'telegram',
                'recipient': '123, 456',
                'bot_token': 'my-token',
                'input_columns': ['col'],
            }
        )
        assert result['bot_token'] == 'my-token'
        assert result['recipient'] == '123, 456'

    def test_bot_token_default_empty(self):
        result = convert_notification_config({'method': 'telegram'})
        assert result['bot_token'] == ''


class TestSendPipelineNotifications:
    def test_output_notification_email(self):
        with patch('modules.compute.service.notification_service') as mock_svc:
            _send_pipeline_notifications(
                pipeline_steps=[],
                context={'analysis_name': 'Test', 'status': 'success', 'datasource_id': 'ds-1'},
                output_notification={
                    'method': 'email',
                    'recipient': 'admin@test.com',
                    'subject_template': 'Build: {{analysis_name}}',
                    'body_template': 'Status: {{status}}',
                },
            )
        mock_svc.send_email.assert_called_once_with(
            to='admin@test.com',
            subject='Build: Test',
            body='Status: success',
        )

    def test_output_notification_telegram(self):
        with (
            patch('modules.compute.service.notification_service') as mock_svc,
            patch('core.database.run_db') as mock_run_db,
        ):
            mock_run_db.side_effect = [[], [MockSubscriber('99999', 'tok')]]
            _send_pipeline_notifications(
                pipeline_steps=[],
                context={'analysis_name': 'A', 'status': 'done', 'datasource_id': 'ds-1'},
                output_notification={
                    'method': 'telegram',
                    'recipient': '',
                    'subject_template': '{{analysis_name}}',
                    'body_template': '{{status}}',
                },
            )
        mock_svc.send_telegram.assert_called_once()
        call_kwargs = mock_svc.send_telegram.call_args.kwargs
        assert call_kwargs['chat_id'] == '99999'
        assert 'A' in call_kwargs['message']
        assert 'done' in call_kwargs['message']

    def test_output_notification_empty_recipient_skipped(self):
        with patch('modules.compute.service.notification_service') as mock_svc:
            _send_pipeline_notifications(
                pipeline_steps=[],
                context={},
                output_notification={
                    'method': 'email',
                    'recipient': '',
                },
            )
        mock_svc.send_email.assert_not_called()

    def test_output_notification_none_skipped(self):
        with patch('modules.compute.service.notification_service') as mock_svc:
            _send_pipeline_notifications(
                pipeline_steps=[],
                context={},
                output_notification=None,
            )
        mock_svc.send_email.assert_not_called()
        mock_svc.send_telegram.assert_not_called()

    def test_output_notification_excluded_recipients(self):
        with patch('modules.compute.service.notification_service') as mock_svc:
            _send_pipeline_notifications(
                pipeline_steps=[],
                context={'analysis_name': 'Test', 'status': 'success', 'datasource_id': 'ds-1'},
                output_notification={
                    'method': 'email',
                    'recipient': 'admin@test.com, skip@test.com',
                    'subject_template': 'Build: {{analysis_name}}',
                    'body_template': 'Status: {{status}}',
                },
            )
        mock_svc.send_email.assert_called_once_with(
            to='admin@test.com, skip@test.com',
            subject='Build: Test',
            body='Status: success',
        )

    def test_output_notification_telegram_uses_subscribers(self):
        with (
            patch('modules.compute.service.notification_service') as mock_svc,
            patch('core.database.run_db') as mock_run_db,
        ):
            mock_run_db.side_effect = [[], [MockSubscriber('111', 'token-a')]]
            _send_pipeline_notifications(
                pipeline_steps=[],
                context={'analysis_name': 'Test', 'status': 'success', 'datasource_id': 'ds-1'},
                output_notification={
                    'method': 'telegram',
                    'recipient': '',
                    'subject_template': 'Build: {{analysis_name}}',
                    'body_template': 'Status: {{status}}',
                },
            )
        mock_svc.send_telegram.assert_called_once()
        message = mock_svc.send_telegram.call_args.kwargs['message']
        assert 'Status: success' in message

    def test_output_notification_telegram_excludes_subscribers(self):
        with (
            patch('modules.compute.service.notification_service') as mock_svc,
            patch('core.database.run_db') as mock_run_db,
        ):
            mock_run_db.side_effect = [[], [MockSubscriber('111', 'token-a')]]
            _send_pipeline_notifications(
                pipeline_steps=[],
                context={'analysis_name': 'Test', 'status': 'success', 'datasource_id': 'ds-1'},
                output_notification={
                    'method': 'telegram',
                    'recipient': '',
                    'subject_template': 'Build: {{analysis_name}}',
                    'body_template': 'Status: {{status}}',
                    'excluded_recipients': ['111'],
                },
            )
        mock_svc.send_telegram.assert_not_called()

    def test_output_notification_error_raises(self):
        with patch('modules.compute.service.notification_service') as mock_svc:
            mock_svc.send_email.side_effect = RuntimeError('SMTP error')
            with pytest.raises(PipelineExecutionError):
                _send_pipeline_notifications(
                    pipeline_steps=[],
                    context={},
                    output_notification={
                        'method': 'email',
                        'recipient': 'x@x.com',
                    },
                )

    def test_skips_per_row_notification_steps(self):
        with patch('modules.compute.service.notification_service') as mock_svc:
            _send_pipeline_notifications(
                pipeline_steps=[
                    {
                        'type': 'notification',
                        'config': {
                            'method': 'email',
                            'recipient': 'x@x.com',
                            'input_columns': ['col'],
                        },
                    },
                ],
                context={},
            )
        mock_svc.send_email.assert_not_called()

    def test_legacy_build_notification_still_works(self):
        with patch('modules.compute.service.notification_service') as mock_svc:
            _send_pipeline_notifications(
                pipeline_steps=[
                    {
                        'type': 'notification',
                        'config': {
                            'method': 'email',
                            'recipient': 'admin@test.com',
                            'subject_template': 'Done',
                            'body_template': 'All good',
                        },
                    },
                ],
                context={},
            )
        mock_svc.send_email.assert_called_once()

    def test_non_notification_steps_ignored(self):
        with patch('modules.compute.service.notification_service') as mock_svc:
            _send_pipeline_notifications(
                pipeline_steps=[
                    {'type': 'filter', 'config': {}},
                    {'type': 'export', 'config': {}},
                ],
                context={},
            )
        mock_svc.send_email.assert_not_called()
        mock_svc.send_telegram.assert_not_called()

    def test_both_output_and_legacy(self):
        with patch('modules.compute.service.notification_service') as mock_svc:
            _send_pipeline_notifications(
                pipeline_steps=[
                    {
                        'type': 'notification',
                        'config': {
                            'method': 'email',
                            'recipient': 'legacy@test.com',
                        },
                    },
                ],
                context={'analysis_name': 'X'},
                output_notification={
                    'method': 'email',
                    'recipient': 'output@test.com',
                },
            )
        assert mock_svc.send_email.call_count == 2


class TestRenderTemplate:
    def test_basic(self):
        assert render_template('Hello {{name}}!', {'name': 'World'}) == 'Hello World!'

    def test_multiple_keys(self):
        result = render_template('{{a}} and {{b}}', {'a': 'foo', 'b': 'bar'})
        assert result == 'foo and bar'

    def test_missing_key_untouched(self):
        assert render_template('{{missing}}', {}) == '{{missing}}'

    def test_numeric(self):
        assert render_template('Count: {{n}}', {'n': 42}) == 'Count: 42'
