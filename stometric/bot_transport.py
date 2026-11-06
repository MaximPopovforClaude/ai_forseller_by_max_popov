"""Telegram transport for a self-hosted installation. Never logs token-bearing URLs."""
import time
import httpx
from . import config

MAX_FILE = 10 * 1024 * 1024


class BotError(RuntimeError):
    pass


class Bot:
    def __init__(self, token_env: str, token: str | None = None):
        self.token = token or config.env().get(token_env)
        self.http = httpx.Client(timeout=40)
        self.username = None
        if self.token:
            try:
                self.username = (self.api('getMe') or {}).get('username')
            except BotError as exc:
                print('Telegram initialization:', str(exc), flush=True)
                self.token = None

    def api(self, method: str, **params):
        if not self.token:
            raise BotError('Telegram bot is not configured')
        try:
            response = self.http.post(f'https://api.telegram.org/bot{self.token}/{method}', json=params)
            data = response.json()
        except Exception:
            raise BotError('Telegram connection or response failed') from None
        if not isinstance(data, dict) or data.get('ok') is not True:
            code = data.get('error_code') if isinstance(data, dict) else None
            code = code if type(code) is int and 100 <= code <= 599 else 'unknown'
            raise BotError(f'Telegram API error {code}')
        return data.get('result')

    def send(self, chat_id, text, **kw):
        return self.send_id(chat_id, text, **kw) is not None

    def send_id(self, chat_id, text, **kw):
        try:
            return self.api('sendMessage', chat_id=chat_id, text=text, parse_mode='HTML',
                            disable_web_page_preview=True, **kw)['message_id']
        except Exception:
            print('Telegram message delivery failed', flush=True)
            return None

    def edit(self, chat_id, msg_id, text, **kw):
        try:
            self.api('editMessageText', chat_id=chat_id, message_id=msg_id, text=text,
                     parse_mode='HTML', disable_web_page_preview=True, **kw)
        except BotError:
            pass

    def doc(self, chat_id, name, raw, caption=''):
        if not self.token or len(raw) > MAX_FILE:
            return False
        try:
            r = self.http.post(f'https://api.telegram.org/bot{self.token}/sendDocument',
                               data={'chat_id': chat_id, 'caption': caption[:1000]},
                               files={'document': (name, raw)})
            return r.json().get('ok') is True
        except Exception:
            print('Telegram file delivery failed', flush=True)
            return False

    def download(self, file_id):
        f = self.api('getFile', file_id=file_id)
        if not isinstance(f, dict) or type(f.get('file_size')) is not int or not 0 <= f['file_size'] <= MAX_FILE:
            raise BotError('Telegram file is missing or exceeds 10 MB')
        path = f.get('file_path')
        if not isinstance(path, str) or not path or path.startswith('/') or '..' in path.split('/'):
            raise BotError('Invalid Telegram file path')
        try:
            with self.http.stream('GET', f'https://api.telegram.org/file/bot{self.token}/{path}') as response:
                response.raise_for_status()
                data = bytearray()
                for part in response.iter_bytes():
                    data.extend(part)
                    if len(data) > MAX_FILE:
                        raise BotError('Telegram file exceeds 10 MB')
                return bytes(data)
        except BotError:
            raise
        except Exception:
            raise BotError('Telegram file download failed') from None

    def poll(self, handle, media=False, on_cb=None):
        offset = 0
        while True:
            try:
                updates = self.api('getUpdates', offset=offset, timeout=25,
                                   allowed_updates=['message'] + (['callback_query'] if on_cb else []))
                for update in updates or []:
                    offset = update['update_id'] + 1
                    cb = update.get('callback_query')
                    if cb and on_cb:
                        chat = cb.get('message', {}).get('chat', {})
                        if chat.get('type') == 'private' and chat.get('id') == cb.get('from', {}).get('id'):
                            try:
                                on_cb(self, cb)
                            except Exception:
                                print('Telegram callback failed', flush=True)
                        continue
                    m = update.get('message')
                    if m and m.get('chat', {}).get('type') == 'private' and (m.get('text') or media and (m.get('photo') or m.get('document'))):
                        try:
                            handle(self, m)
                        except Exception:
                            print('Telegram message handler failed', flush=True)
                            self.send(m['chat']['id'], 'Не получилось обработать сообщение. Проверьте статус перед повтором.')
            except Exception:
                print('Telegram polling failed; check token, webhook and duplicate processes', flush=True)
                time.sleep(5)
