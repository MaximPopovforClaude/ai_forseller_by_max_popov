"""Shared durable request identities and short enqueue locks; never runs models."""
import re

TASK_QUEUE_LOCK_NAMESPACE = 1095324241
REPORT_QUEUE_LOCK_NAMESPACE = 1095324242
REQUEST_KEY = re.compile(r'[A-Za-z0-9_.:-]{1,200}\Z')


def validate_key(key):
    if key is not None and (type(key) is not str or not REQUEST_KEY.fullmatch(key)):
        raise ValueError('Invalid analytics request key')


def lock_queue(c, kind, shop):
    """Held until the caller commits/rolls back the short claim transaction."""
    namespace = {'tasks': TASK_QUEUE_LOCK_NAMESPACE, 'reports': REPORT_QUEUE_LOCK_NAMESPACE}[kind]
    c.execute('SELECT pg_advisory_xact_lock(%s,%s)', (namespace, shop))


def reference(c, key, kind, shop, actor):
    validate_key(key)
    if key is None:
        return None
    row = c.execute('SELECT kind,account_id,actor_id,run_id FROM ai_analytics_request_refs WHERE request_key=%s',
                    (key,)).fetchone()
    if row and (row['kind'], row['account_id'], row['actor_id']) != (kind, shop, actor):
        raise ValueError('Analytics request key belongs to a different request')
    return row['run_id'] if row else None


def remember(c, key, kind, shop, actor, run_id):
    validate_key(key)
    if key is None:
        return
    c.execute('''INSERT INTO ai_analytics_request_refs(request_key,kind,account_id,actor_id,run_id)
                 VALUES (%s,%s,%s,%s,%s) ON CONFLICT (request_key) DO NOTHING''',
              (key, kind, shop, actor, run_id))
    if reference(c, key, kind, shop, actor) != run_id:
        raise ValueError('Analytics request key already refers to another execution')
