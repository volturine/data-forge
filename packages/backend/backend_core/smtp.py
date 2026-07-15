"""Shared SMTP delivery helpers."""

import smtplib
from email.message import EmailMessage

_SMTP_SSL_PORT = 465


def send_smtp_message(host: str, port: int, user: str, password: str, msg: EmailMessage, timeout: int = 10) -> None:
    """Send an email with sensible TLS behavior for common SMTP configurations."""
    if port == _SMTP_SSL_PORT:
        with smtplib.SMTP_SSL(host, port, timeout=timeout) as server:
            if password:
                server.login(user, password)
            server.send_message(msg)
        return

    with smtplib.SMTP(host, port, timeout=timeout) as server:
        server.ehlo()
        if server.has_extn('starttls'):
            server.starttls()
            server.ehlo()
        if password:
            server.login(user, password)
        server.send_message(msg)
