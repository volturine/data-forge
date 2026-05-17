from email.message import EmailMessage
from unittest.mock import MagicMock, patch

from core.smtp import send_smtp_message


def _message() -> EmailMessage:
    msg = EmailMessage()
    msg['From'] = 'from@example.com'
    msg['To'] = 'to@example.com'
    msg['Subject'] = 'subject'
    msg.set_content('body')
    return msg


def test_send_smtp_message_uses_implicit_ssl_for_port_465() -> None:
    msg = _message()
    with patch('core.smtp.smtplib.SMTP') as mock_smtp, patch('core.smtp.smtplib.SMTP_SSL') as mock_smtp_ssl:
        server = MagicMock()
        mock_smtp_ssl.return_value.__enter__.return_value = server
        send_smtp_message('smtp.example.com', 465, 'user@example.com', 'secret', msg)

    mock_smtp.assert_not_called()
    mock_smtp_ssl.assert_called_once_with('smtp.example.com', 465, timeout=10)
    server.starttls.assert_not_called()
    server.login.assert_called_once_with('user@example.com', 'secret')
    server.send_message.assert_called_once_with(msg)


def test_send_smtp_message_uses_starttls_when_advertised() -> None:
    msg = _message()
    with patch('core.smtp.smtplib.SMTP') as mock_smtp:
        server = MagicMock()
        server.has_extn.return_value = True
        mock_smtp.return_value.__enter__.return_value = server
        send_smtp_message('smtp.example.com', 587, 'user@example.com', 'secret', msg)

    mock_smtp.assert_called_once_with('smtp.example.com', 587, timeout=10)
    server.ehlo.assert_called()
    assert server.ehlo.call_count == 2
    server.starttls.assert_called_once()
    server.login.assert_called_once_with('user@example.com', 'secret')
    server.send_message.assert_called_once_with(msg)


def test_send_smtp_message_skips_starttls_when_not_advertised() -> None:
    msg = _message()
    with patch('core.smtp.smtplib.SMTP') as mock_smtp:
        server = MagicMock()
        server.has_extn.return_value = False
        mock_smtp.return_value.__enter__.return_value = server
        send_smtp_message('smtp.example.com', 587, 'user@example.com', '', msg)

    mock_smtp.assert_called_once_with('smtp.example.com', 587, timeout=10)
    server.ehlo.assert_called_once()
    server.starttls.assert_not_called()
    server.login.assert_not_called()
    server.send_message.assert_called_once_with(msg)
