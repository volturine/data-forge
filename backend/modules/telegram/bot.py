"""Telegram bot — long-polling thread for /subscribe and /unsubscribe."""

import logging
import threading
import time

import httpx

logger = logging.getLogger(__name__)

_TELEGRAM_BASE = 'https://api.telegram.org'


class TelegramBot:
    """Runs an indefinite polling loop in a background thread."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._token: str = ''

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def token(self) -> str:
        return self._token

    def start(self, token: str) -> None:
        if self.running:
            self.stop()
        self._token = token
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name='telegram-bot')
        self._thread.start()
        logger.info('Telegram bot polling started')

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None
        logger.info('Telegram bot polling stopped')

    def _poll_loop(self) -> None:
        offset = 0
        consecutive_errors = 0
        max_consecutive_errors = 10
        while not self._stop_event.is_set():
            try:
                resp = httpx.get(
                    f'{_TELEGRAM_BASE}/bot{self._token}/getUpdates',
                    params={'offset': offset, 'timeout': 30},
                    timeout=40,
                )
                if resp.status_code == 401:
                    logger.error('Telegram bot token is invalid (401 Unauthorized) — stopping bot')
                    break
                if resp.status_code != 200:
                    consecutive_errors += 1
                    logger.warning(
                        'Telegram getUpdates failed: %s (error %d/%d)', resp.status_code, consecutive_errors, max_consecutive_errors
                    )
                    if consecutive_errors >= max_consecutive_errors:
                        logger.error('Telegram bot hit %d consecutive errors — stopping', max_consecutive_errors)
                        break
                    time.sleep(5)
                    continue
                consecutive_errors = 0
                data = resp.json()
                for update in data.get('result', []):
                    offset = update['update_id'] + 1
                    self._handle_update(update)
            except httpx.TimeoutException:
                continue
            except Exception:
                consecutive_errors += 1
                logger.exception('Telegram bot error (%d/%d)', consecutive_errors, max_consecutive_errors)
                if consecutive_errors >= max_consecutive_errors:
                    logger.error('Telegram bot hit %d consecutive errors — stopping', max_consecutive_errors)
                    break
                time.sleep(5)

    def _handle_update(self, update: dict) -> None:
        msg = update.get('message')
        if not msg:
            return
        text = msg.get('text', '')
        chat = msg.get('chat', {})
        chat_id = str(chat.get('id', ''))
        title = str(chat.get('first_name') or chat.get('title') or chat.get('username') or chat_id)

        command = text.strip().lower()
        if command == '/subscribe':
            self._handle_subscribe(chat_id, title)
        elif command == '/unsubscribe':
            self._handle_unsubscribe(chat_id)
        elif command == '/start':
            self._send_message(chat_id, 'Welcome! Use /subscribe to receive build notifications.')

    def _handle_subscribe(self, chat_id: str, title: str) -> None:
        from core.database import run_db
        from modules.telegram.service import add_subscriber

        def _add(session) -> None:  # type: ignore[no-untyped-def]
            add_subscriber(session, chat_id, title, self._token)

        try:
            run_db(_add)
            self._send_message(chat_id, 'Subscribed! You will receive build notifications.')
            logger.info('Telegram subscriber added: %s (%s)', chat_id, title)
        except Exception:
            logger.exception('Failed to add subscriber %s', chat_id)
            self._send_message(chat_id, 'Failed to subscribe. Please try again.')

    def _handle_unsubscribe(self, chat_id: str) -> None:
        from core.database import run_db
        from modules.telegram.service import get_subscriber_by_chat

        def _remove(session) -> None:  # type: ignore[no-untyped-def]
            sub = get_subscriber_by_chat(session, chat_id, self._token)
            if sub:
                sub.is_active = False
                session.add(sub)
                session.commit()

        try:
            run_db(_remove)
            self._send_message(chat_id, 'Unsubscribed. You will no longer receive notifications.')
            logger.info('Telegram subscriber deactivated: %s', chat_id)
        except Exception:
            logger.exception('Failed to unsubscribe %s', chat_id)

    def _send_message(self, chat_id: str, text: str) -> None:
        try:
            httpx.post(
                f'{_TELEGRAM_BASE}/bot{self._token}/sendMessage',
                json={'chat_id': chat_id, 'text': text},
                timeout=10,
            )
        except Exception:
            logger.warning('Failed to send message to %s', chat_id)


# Global singleton
telegram_bot = TelegramBot()
