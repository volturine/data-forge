import logging
import threading
import time

import httpx

from core import http as http_client

logger = logging.getLogger(__name__)

_TELEGRAM_BASE = 'https://api.telegram.org'


class TelegramBot:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._token: str = ''
        self._poll_lock = threading.Lock()
        self._offset_lock = threading.Lock()
        self._offset_by_token: dict[str, int] = {}

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def token(self) -> str:
        return self._token

    def start(self, token: str) -> None:
        if self.running:
            self.stop()
        if self.running:
            logger.warning('Telegram bot stop in progress; start skipped')
            return
        self._token = token
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name='telegram-bot')
        self._thread.start()
        logger.info('Telegram bot polling started')

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            # Use a short join timeout. The poll loop checks _stop_event
            # and uses short poll timeouts when stopping, so it should
            # exit within a few seconds.
            self._thread.join(timeout=10)
        if self._thread and self._thread.is_alive():
            logger.warning('Telegram bot did not stop before timeout')
            return
        self._thread = None
        logger.info('Telegram bot polling stopped')

    def pause(self) -> None:
        if not self.running:
            return
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        if self._thread and not self._thread.is_alive():
            self._thread = None

    def resume(self) -> None:
        if not self._token:
            return
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name='telegram-bot')
        self._thread.start()

    def _poll_loop(self) -> None:
        consecutive_errors = 0
        max_consecutive_errors = 10
        offset = self._get_offset(self._token)
        while not self._stop_event.is_set():
            poll_timeout = 5 if self._stop_event.is_set() else 30
            try:
                resp = self._do_get_updates(
                    self._token,
                    params={'offset': offset, 'timeout': poll_timeout},
                    timeout=poll_timeout + 10,
                )
                if resp is None:
                    # Lock not acquired — another caller is using it
                    time.sleep(1)
                    continue
                if resp.status_code == 401:
                    logger.error('Telegram bot token is invalid (401 Unauthorized) — stopping bot')
                    break
                if resp.status_code == 409:
                    consecutive_errors += 1
                    logger.warning(
                        'Telegram getUpdates conflict (409) — another poller or webhook is active (error %d/%d)',
                        consecutive_errors,
                        max_consecutive_errors,
                    )
                    self._clear_webhook(self._token)
                    if consecutive_errors >= max_consecutive_errors:
                        logger.error('Telegram bot hit %d consecutive errors — stopping', max_consecutive_errors)
                        break
                    time.sleep(5)
                    continue
                if resp.status_code != 200:
                    consecutive_errors += 1
                    logger.warning(
                        'Telegram getUpdates failed: %s (error %d/%d)',
                        resp.status_code,
                        consecutive_errors,
                        max_consecutive_errors,
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
                    self._set_offset(self._token, offset)
                    self._handle_update(update)
            except httpx.TimeoutException:
                continue
            except Exception as exc:
                consecutive_errors += 1
                logger.exception('Telegram bot error (%d/%d): %s', consecutive_errors, max_consecutive_errors, exc)
                if consecutive_errors >= max_consecutive_errors:
                    logger.error('Telegram bot hit %d consecutive errors — stopping', max_consecutive_errors)
                    break
                time.sleep(5)

    def _do_get_updates(
        self,
        token: str,
        params: dict[str, int],
        timeout: float,
    ) -> httpx.Response | None:
        acquired = self._poll_lock.acquire(timeout=2)
        if not acquired:
            return None
        try:
            return http_client.get(
                f'{_TELEGRAM_BASE}/bot{token}/getUpdates',
                params=params,
                timeout=timeout,
            )
        finally:
            self._poll_lock.release()

    def get_updates(self, token: str, params: dict[str, int], timeout: float) -> httpx.Response:
        with self._poll_lock:
            return http_client.get(
                f'{_TELEGRAM_BASE}/bot{token}/getUpdates',
                params=params,
                timeout=timeout,
            )

    def get_offset(self, token: str) -> int:
        return self._get_offset(token)

    def _clear_webhook(self, token: str) -> None:
        try:
            http_client.post(
                f'{_TELEGRAM_BASE}/bot{token}/deleteWebhook',
                json={'drop_pending_updates': False},
                timeout=10,
            )
        except Exception as exc:
            logger.warning('Failed to clear Telegram webhook for token: %s', exc)

    def _get_offset(self, token: str) -> int:
        with self._offset_lock:
            return self._offset_by_token.get(token, 0)

    def _set_offset(self, token: str, offset: int) -> None:
        with self._offset_lock:
            self._offset_by_token[token] = offset

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
        except Exception as exc:
            logger.exception('Failed to add subscriber %s: %s', chat_id, exc)
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
        except Exception as exc:
            logger.exception('Failed to unsubscribe %s: %s', chat_id, exc)

    def _send_message(self, chat_id: str, text: str) -> None:
        try:
            http_client.post(
                f'{_TELEGRAM_BASE}/bot{self._token}/sendMessage',
                json={'chat_id': chat_id, 'text': text},
                timeout=10,
            )
        except Exception as exc:
            logger.warning('Failed to send message to %s: %s', chat_id, exc)


# Global singleton
telegram_bot = TelegramBot()
