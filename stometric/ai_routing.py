"""Self-hosted AI uses the current workspace's own encrypted API key only."""


def shop_route(c, shop_id, actor_id=None):
    actor_id = actor_id if actor_id is not None else getattr(c, '_ai_actor_id', None)
    scheduled = getattr(c, '_ai_trusted_scheduled', False) is True
    row = c.execute('''SELECT a.workspace_id,w.plan,a.is_active,
        EXISTS(SELECT 1 FROM memberships m JOIN users u ON u.id=m.user_id
            WHERE m.workspace_id=a.workspace_id AND m.user_id=%s AND u.is_active
            AND (m.shop_ids IS NULL OR a.id=ANY(m.shop_ids))) member,
        EXISTS(SELECT 1 FROM workspace_secrets s WHERE s.workspace_id=a.workspace_id AND s.kind='claude') has_key
        FROM accounts a JOIN workspaces w ON w.id=a.workspace_id WHERE a.id=%s''', (actor_id, shop_id)).fetchone()
    ready = bool(row and row['is_active'] and row['has_key'] and (row['member'] or (actor_id is None and scheduled)))
    return {'plan': row['plan'] if row else None, 'workspace_id': row['workspace_id'] if row else None,
            'ai_route': 'workspace_api', 'ai_ready': ready,
            'ai_reason': None if ready else 'Нужен API-ключ нейросети аккаунта и действующий доступ к магазину.'}


def workspace_route(c, workspace_id, actor_id=None):
    for row in c.execute('SELECT id FROM accounts WHERE workspace_id=%s AND is_active ORDER BY id', (workspace_id,)).fetchall():
        route = shop_route(c, row['id'], actor_id)
        if route['ai_ready']:
            return route
    return {'workspace_id': workspace_id, 'ai_route': 'workspace_api', 'ai_ready': False,
            'ai_reason': 'Подключите API-ключ в настройках аккаунта и добавьте магазин.'}
