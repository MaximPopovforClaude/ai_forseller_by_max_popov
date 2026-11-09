"""Explicit personal owner scope. No credentials and no commercial fallback."""
import json
from datetime import datetime, timezone
from uuid import uuid4

SETTING = 'personal_owner_ai'
TITLE = 'VIP (личная подписка владельца)'


def settings(c):
    row = c.execute('SELECT value FROM app_settings WHERE key=%s', (SETTING,)).fetchone()
    return row['value'] if row and isinstance(row['value'], dict) else {}


def owns(c, workspace, uid):
    return bool(c.execute('''SELECT 1 FROM memberships m JOIN users u ON u.id=m.user_id
        WHERE m.workspace_id=%s AND m.user_id=%s AND m.role='owner' AND u.is_active
        AND u.is_superadmin AND m.shop_ids IS NULL''', (workspace, uid)).fetchone())


def allowed(c, shop, actor_id=None, *, scheduled=False):
    cfg = settings(c)
    if type(shop) is not int or cfg.get('enabled') is not True or shop not in cfg.get('shop_ids', []):
        return False
    uid = cfg.get('owner_user_id')
    if type(uid) is not int or not ((actor_id == uid and type(actor_id) is int) or (actor_id is None and scheduled is True)):
        return False
    if not owns(c, cfg.get('workspace_id'), uid):
        return False
    row = c.execute('''SELECT a.workspace_id,a.is_active,a.archived_at,w.plan FROM accounts a
        JOIN workspaces w ON w.id=a.workspace_id WHERE a.id=%s''', (shop,)).fetchone()
    return bool(row and row['workspace_id'] == cfg.get('workspace_id') and row['is_active']
                and row['archived_at'] is None and row['plan'] == 'owner')


class OwnerKey(str):
    def __new__(cls, shop, actor_id, scheduled, revision):
        obj = super().__new__(cls, 'subscription')
        obj.shop, obj.actor_id, obj.scheduled, obj.revision = shop, actor_id, scheduled, revision
        return obj


def key_for(c, shop, actor_id=None):
    actor_id = actor_id if actor_id is not None else getattr(c, '_ai_actor_id', None)
    scheduled = actor_id is None and getattr(c, '_ai_trusted_scheduled', False) is True
    if not allowed(c, shop, actor_id, scheduled=scheduled):
        return None
    return OwnerKey(shop, actor_id, scheduled, settings(c).get('revision'))


def recheck(key):
    if not isinstance(key, OwnerKey):
        raise RuntimeError('Для личного ИИ нужен подтверждённый магазин владельца.')
    from . import db
    with db.connect() as c:
        cfg = settings(c)
        if cfg.get('revision') != key.revision or not allowed(c, key.shop, key.actor_id, scheduled=key.scheduled):
            raise RuntimeError('Доступ к личной подписке изменился. Задание остановлено.')
        return cfg


def require_personal_chat(c, chat_id):
    since = settings(c).get('scope_since')
    if not since or not c.execute('SELECT 1 FROM assistant_chats WHERE id=%s AND created_at >= %s::timestamptz', (chat_id, since)).fetchone():
        raise RuntimeError('После включения VIP или изменения магазинов создайте новый чат Стометрика. История прежнего маршрута сохранена отдельно.')


def save(c, uid, workspace, shops, enabled, readiness):
    from fastapi import HTTPException
    # Serialize configuration/plan changes; no automatic reassignment to another owner.
    c.execute('SELECT pg_advisory_xact_lock(11876433)')
    old = settings(c)
    if old.get('owner_user_id') not in (None, uid):
        raise HTTPException(403, 'Личный ИИ уже настроен другим владельцем этой установки.')
    if not owns(c, workspace, uid):
        raise HTTPException(403, 'Выберите свой кабинет с полной ролью владельца.')
    shops = sorted(set(shops))
    valid = {r['id'] for r in c.execute('''SELECT id FROM accounts WHERE workspace_id=%s
        AND is_active AND archived_at IS NULL AND id=ANY(%s)''', (workspace, shops)).fetchall()}
    if set(shops) != valid or (enabled and not shops):
        raise HTTPException(400, 'Выберите действующие магазины своего кабинета.')
    if enabled and not readiness.get('text_ready'):
        raise HTTPException(409, readiness.get('reason') or 'Сначала подключите личный Codex на сервере.')
    cfg = {'owner_user_id': uid, 'workspace_id': workspace, 'shop_ids': shops, 'enabled': enabled,
           'revision': str(uuid4()), 'text_ready': bool(readiness.get('text_ready')),
           'image_ready': bool(readiness.get('image_ready')), 'image_reason': readiness.get('image_reason'),
           'model': readiness.get('model'), 'checked_at': readiness.get('checked_at')}
    same_scope = old.get('enabled') and old.get('workspace_id') == workspace and old.get('shop_ids') == shops
    cfg['scope_since'] = old.get('scope_since') if same_scope and old.get('scope_since') else datetime.now(timezone.utc).isoformat()
    c.execute('''INSERT INTO app_settings(key,value) VALUES (%s,%s)
        ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value''', (SETTING, json.dumps(cfg)))
    if enabled:
        c.execute("UPDATE workspaces SET plan='owner',plan_until=NULL,plan_changed_at=now() WHERE id=%s", (workspace,))
    return cfg
