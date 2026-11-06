"""Read-only checks on YOUR installation. No messages, AI calls, token output or writes."""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def inspect(c, user, shop, telegram=False):
    from stometric import ai_routing, bots, config
    from stometric.bot_runtime import settings
    url = urlsplit(config.site_url())
    route = ai_routing.shop_route(c, shop, user)
    meta = c.execute("""SELECT value->>'username' username,
                         coalesce(length(value->>'enc'),0)>0 configured
                         FROM app_settings WHERE key='tg_assistant_bot'""").fetchone() or {}
    link = c.execute("""SELECT u.is_active, u.telegram_id IS NOT NULL linked,
                         coalesce(s.bot='assistant' AND s.chat_id=u.telegram_id, false) receives
                         FROM users u LEFT JOIN notify_settings s ON s.user_id=u.id WHERE u.id=%s""", (user,)).fetchone() or {}
    result = {'site_https': url.scheme == 'https' and bool(url.hostname),
              'user_active': bool(link.get('is_active')), 'ai_ready': route['ai_ready'],
              'ai_route': route['ai_route'], 'ai_reason': route.get('ai_reason'),
              'telegram_configured': bool(meta.get('configured')), 'bot_username': meta.get('username'),
              'user_linked': bool(link.get('linked')), 'notifications_recipient': bool(link.get('receives')),
              'jobs': settings(c), 'telegram_checked': False}
    if telegram:
        token = bots.assistant_token(c)
        if token:
            bot = bots.Bot('', token)
            try:
                if not bot.token:
                    result['telegram_error'] = 'bot_authentication_failed'
                else:
                    info = bot.api('getWebhookInfo')
                    result.update(telegram_checked=True, bot_matches=bot.username == meta.get('username'),
                                  webhook_present=bool((info or {}).get('url')))
                    # Neither webhook URLs nor errors from Telegram are copied to output.
            except Exception:
                result['telegram_error'] = 'telegram_check_failed'
            finally:
                bot.http.close()
        else:
            result['telegram_error'] = 'token_missing_or_cannot_decrypt'
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--user', type=int, required=True, help='Your user ID from your admin page')
    p.add_argument('--shop', type=int, required=True, help='Your shop ID')
    p.add_argument('--telegram', action='store_true', help='Also call getMe/getWebhookInfo; no sends or changes')
    args = p.parse_args()
    if args.user <= 0 or args.shop <= 0:
        p.error('IDs must be positive')
    try:
        import stometric.web
        from stometric import db
        with db.connect(readonly=True, timeout_s=15) as c:
            result = inspect(c, args.user, args.shop, args.telegram)
    except Exception:
        print(json.dumps({'error': 'local_check_failed', 'hint': 'Check migrations, database access and local configuration; do not share secrets.'}))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    ready = all(result[k] for k in ('site_https','user_active','ai_ready','telegram_configured','user_linked'))
    if args.telegram:
        ready = ready and result.get('telegram_checked') and result.get('bot_matches') and not result.get('webhook_present')
    return 0 if ready else 1


if __name__ == '__main__':
    raise SystemExit(main())
