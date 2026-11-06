"""Shared calendar; permission checks also apply at reminder delivery time."""
import html
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from . import auth, manager
from .config import today_msk

WRITE_ROLES = ('editor', 'admin', 'owner')


def scope(c, u, ws, write=False):
    
    
    if not u or not u.get('is_active', True) or u.get('_mcp'):
        raise HTTPException(403, 'Календарь доступен участникам аккаунта на сайте')
    m = c.execute('SELECT role,shop_ids FROM memberships WHERE workspace_id=%s AND user_id=%s', (ws, u['id'])).fetchone()
    if not m or (write and m['role'] not in WRITE_ROLES):
        raise HTTPException(403, 'Для изменения календаря нужна роль «редактор» или выше' if m else 'Нет доступа к аккаунту')
    shops = c.execute('''SELECT id,coalesce(title,name) title,marketplace FROM accounts
                         WHERE workspace_id=%s AND is_active AND (%s::int[] IS NULL OR id=ANY(%s)) ORDER BY id''',
                      (ws, m['shop_ids'], m['shop_ids'])).fetchall()
    return {**m, 'shops': shops, 'ids': [s['id'] for s in shops]}


def members(c, ws):
    return c.execute('''SELECT u.id,coalesce(nullif(u.name,''),u.email) name,m.role,m.shop_ids
                        FROM memberships m JOIN users u ON u.id=m.user_id AND u.is_active
                        WHERE m.workspace_id=%s AND m.role=ANY(%s) ORDER BY 2,u.id''', (ws, list(WRITE_ROLES))).fetchall()


def editable(u, ctx, entry):
    return ctx['role'] in WRITE_ROLES and (ctx['role'] in ('owner', 'admin') or u['id'] in (entry['created_by'], entry['assignee_id']))


FIELDS = '''e.*, coalesce(nullif(a.name,''),a.email) author,
            coalesce(nullif(p.name,''),p.email) assignee, coalesce(s.title,s.name) shop,
            r.state reminder_state'''
JOINS = '''LEFT JOIN users a ON a.id=e.created_by LEFT JOIN users p ON p.id=e.assignee_id
           LEFT JOIN accounts s ON s.id=e.shop_id
           LEFT JOIN calendar_reminders r ON r.entry_id=e.id AND r.reminder_version=e.reminder_version'''


def entries(c, u, ws, ctx, start=None, end=None, closed=False, mine=False, due=False, shop=None):
    if shop is not None and shop not in ctx['ids']:
        raise HTTPException(403, 'Нет доступа к магазину')
    where = ['e.workspace_id=%(ws)s', '(e.shop_id IS NULL OR e.shop_id=ANY(%(ids)s))']
    args = {'ws': ws, 'ids': ctx['ids'], 'uid': u['id'], 'start': start, 'end': end,
            'tomorrow': today_msk() + timedelta(days=1), 'shop': shop}
    if due:
        where += ["e.kind='task'", "e.status='open'", 'e.assignee_id=%(uid)s', 'e.day<=%(tomorrow)s']
    else:
        where += ['e.day BETWEEN %(start)s AND %(end)s']
        if not closed:
            where += ["e.status='open'"]
        if mine:
            where += ['(e.assignee_id=%(uid)s OR e.created_by=%(uid)s)']
    if shop is not None:
        where += ['e.shop_id=%(shop)s']
    rows = c.execute(f'''SELECT {FIELDS} FROM calendar_entries e {JOINS}
                         WHERE {' AND '.join(where)} ORDER BY e.day,e.id LIMIT 2001''', args).fetchall()
    return [{'can_edit': editable(u, ctx, e), **e} for e in rows[:2000]], len(rows) > 2000


def check_values(c, ws, ctx, values, closing_assignee=None):
    v = dict(values)
    v['title'] = v['title'].strip()
    if not v['title']:
        raise HTTPException(400, 'Введите название')
    if v['shop_id'] is not None and v['shop_id'] not in ctx['ids']:
        raise HTTPException(403, 'Нет доступа к магазину')
    if v['kind'] == 'note':
        if v['assignee_id'] is not None:
            raise HTTPException(400, 'Для заметки исполнитель не нужен')
        if v.get('status') == 'done':
            raise HTTPException(400, 'У заметки нет статуса выполнения; её можно отменить')
    else:
        allowed = members(c, ws)
        person = next((m for m in allowed if m['id'] == v['assignee_id']), None)
        closing_old = v.get('status') in ('done', 'cancelled') and v['assignee_id'] == closing_assignee
        if not closing_old and (not person or (v['shop_id'] is not None and person['shop_ids'] is not None and v['shop_id'] not in person['shop_ids'])):
            raise HTTPException(400, 'Исполнитель должен иметь доступ к этому аккаунту и магазину и роль «редактор» или выше')
    return v


def create(c, u, ws, values, request_key):
    ctx = scope(c, u, ws, True)
    v = check_values(c, ws, ctx, values)
    row = c.execute('''INSERT INTO calendar_entries(workspace_id,shop_id,kind,title,description,day,assignee_id,created_by,request_key)
                       VALUES (%(ws)s,%(shop_id)s,%(kind)s,%(title)s,%(description)s,%(day)s,%(assignee_id)s,%(uid)s,%(key)s)
                       ON CONFLICT (workspace_id,created_by,request_key) DO NOTHING RETURNING id''',
                    {**v, 'ws': ws, 'uid': u['id'], 'key': request_key}).fetchone()
    if row:
        return row['id'], True
    row = c.execute('SELECT * FROM calendar_entries WHERE workspace_id=%s AND created_by=%s AND request_key=%s',
                    (ws, u['id'], request_key)).fetchone()
    if not row or any(row[k] != value for k, value in v.items()):
        raise HTTPException(409, 'Этот запрос уже сохранён с другим содержимым. Обновите календарь')
    return row['id'], False


def update(c, u, ws, eid, values, version):
    ctx = scope(c, u, ws, True)
    row = c.execute('''SELECT * FROM calendar_entries WHERE id=%s AND workspace_id=%s
                       AND (shop_id IS NULL OR shop_id=ANY(%s)) FOR UPDATE''', (eid, ws, ctx['ids'])).fetchone()
    if not row:
        raise HTTPException(404, 'Запись не найдена')
    if not editable(u, ctx, row):
        raise HTTPException(403, 'Изменить запись может автор, исполнитель или администратор')
    if row['version'] != version:
        raise HTTPException(409, 'Запись уже изменил другой пользователь. Обновите календарь перед сохранением')
    if values['kind'] != row['kind']:
        raise HTTPException(400, 'Вид существующей записи менять нельзя')
    v = check_values(c, ws, ctx, values, closing_assignee=row['assignee_id'])
    new_reminder = (v['day'] != row['day'] or v['assignee_id'] != row['assignee_id']
                    or (row['status'] != 'open' and v['status'] == 'open'))
    c.execute('''UPDATE calendar_entries SET shop_id=%(shop_id)s,title=%(title)s,description=%(description)s,
                 day=%(day)s,assignee_id=%(assignee_id)s,status=%(status)s,version=version+1,
                 reminder_version=reminder_version+%(bump)s,updated_at=now() WHERE id=%(id)s''',
              {**v, 'id': eid, 'bump': int(new_reminder)})




ACTION_SOURCES = '''
 SELECT 'manual' source, x.id::text id,x.account_id shop_id,x.nm_id,x.day,to_jsonb(x) body
 FROM nm_actions x WHERE x.account_id=ANY(%(ids)s) AND x.day BETWEEN %(start)s AND %(end)s
 UNION ALL
 SELECT 'change',x.id::text,x.account_id,x.nm_id,(x.detected_at AT TIME ZONE 'Europe/Moscow')::date,
        jsonb_build_object('kind',x.kind,'field',x.field,'old_value',x.old_value,'new_value',x.new_value)
 FROM card_changes x WHERE x.account_id=ANY(%(ids)s)
 AND x.detected_at >= (%(start)s::date::timestamp AT TIME ZONE 'Europe/Moscow')
 AND x.detected_at < ((%(end)s::date+1)::timestamp AT TIME ZONE 'Europe/Moscow')
 UNION ALL
 SELECT 'promo',x.nm_id::text,x.account_id,x.nm_id,x.day,jsonb_build_object('promos',x.promos)
 FROM wb_promo_days x WHERE x.account_id=ANY(%(ids)s) AND x.day BETWEEN %(start)s AND %(end)s
 UNION ALL
 SELECT 'entry',concat(x.nm_id,':',x.section,':',x.point),x.account_id,x.nm_id,x.day,
        jsonb_build_object('section',x.section,'point',x.point,'clicks',x.clicks,'clicks_avg',x.clicks_avg,'change_pct',x.change_pct)
 FROM entry_alerts x WHERE x.account_id=ANY(%(ids)s) AND x.day BETWEEN %(start)s AND %(end)s
'''


def action_args(ctx, start, end, shop=None):
    if shop is not None and shop not in ctx['ids']:
        raise HTTPException(403, 'Нет доступа к магазину')
    ids = [s['id'] for s in ctx['shops'] if s['marketplace'] in ('wb', 'ozon') and (shop is None or s['id'] == shop)]
    return {'ids': ids, 'start': start, 'end': end}


def action_counts(c, ctx, start, end, shop=None):
    args = action_args(ctx, start, end, shop)
    return c.execute(f'SELECT day,count(*) n FROM ({ACTION_SOURCES}) q GROUP BY day ORDER BY day', args).fetchall() if args['ids'] else []


def action_page(c, ctx, day, shop=None, offset=0):
    args = {**action_args(ctx, day, day, shop), 'offset': offset}
    if not args['ids']:
        return {'items': [], 'more': False}
    rows = c.execute(f'''SELECT q.*,coalesce(a.title,a.name) shop FROM ({ACTION_SOURCES}) q
                         JOIN accounts a ON a.id=q.shop_id ORDER BY q.shop_id,q.nm_id,q.source,q.id
                         LIMIT 201 OFFSET %(offset)s''', args).fetchall()
    titles = {k['key']: k['title'] for k in manager.KINDS}
    out = []
    for r in rows[:200]:
        b, src = r['body'], r['source']
        if src == 'manual':
            title = titles.get(b['kind'], b['kind'].removeprefix('custom:'))
            title += (' · ' + b['value']) if b.get('value') else ''
            note = b.get('note') or ''
        elif src == 'change':
            title, note = manager.change_label(b), 'Из журнала изменений'
        elif src == 'promo':
            title, note = 'В акции: ' + ', '.join(sorted(b['promos'])), 'Из листа действий'
        else:
            title = f"Точка входа {b['section']} / {b['point']}: {float(b['clicks_avg']):.0f} → {float(b['clicks']):.0f} переходов ({b['change_pct']} %)"
            note = 'Из листа действий'
        out.append({k: r[k] for k in ('id', 'source', 'shop_id', 'nm_id', 'day', 'shop')} | {'title': title, 'description': note})
    return {'items': out, 'more': len(rows) > 200}


ELIGIBLE = '''SELECT e.*,ns.chat_id,ns.send_from,ns.send_to,w.name workspace
 FROM calendar_entries e JOIN memberships m ON m.workspace_id=e.workspace_id AND m.user_id=e.assignee_id
 JOIN users u ON u.id=e.assignee_id AND u.is_active
 JOIN notify_settings ns ON ns.user_id=u.id AND ns.bot='assistant' AND ns.chat_id IS NOT NULL
 JOIN workspaces w ON w.id=e.workspace_id
 WHERE e.kind='task' AND e.status='open' AND e.day<=%(tomorrow)s AND m.role=ANY(%(roles)s)
 AND (e.shop_id IS NULL OR NOT e.shop_id=ANY(coalesce(ns.muted_shops,'{}'::int[])))
 AND (e.shop_id IS NULL OR ((m.shop_ids IS NULL OR e.shop_id=ANY(m.shop_ids))
      AND EXISTS (SELECT 1 FROM accounts a WHERE a.id=e.shop_id AND a.workspace_id=e.workspace_id AND a.is_active)))
'''


def reminder_text(e, today):
    label = 'Срок завтра' if e['day'] > today else ('Срок сегодня' if e['day'] == today else 'Срок прошёл')
    return (f"📅 <b>{label}: {e['day']:%d.%m.%Y}</b>\n{html.escape(e['title'])}\n"
            f"Аккаунт: {html.escape(e['workspace'])}\n"
            'Откройте platform.example.org → Аккаунт → Календарь, чтобы посмотреть задачу и отметить выполнение.')


def send_reminders(c, bot, now=None):
    """Only the connected Stometric bot. No manual sending during deployment/tests.

    A reserved delivery is never retried automatically after an ambiguous failure.
    We reread permissions/status and lock them before the external send.
    """
    from .bots import in_window
    if bot is None or not bot.token:
        return 0
    supplied_now = now
    now = now or datetime.now(auth.MSK)
    now = now.astimezone(auth.MSK)
    params = {'tomorrow': now.date() + timedelta(days=1), 'roles': list(WRITE_ROLES), 'clock': now.time().replace(tzinfo=None)}
    candidates = c.execute(ELIGIBLE + ''' AND NOT EXISTS (SELECT 1 FROM calendar_reminders r
        WHERE r.entry_id=e.id AND r.reminder_version=e.reminder_version AND r.state<>'deferred')
        AND (ns.send_from=ns.send_to OR (ns.send_from<ns.send_to AND %(clock)s>=ns.send_from AND %(clock)s<ns.send_to)
             OR (ns.send_from>ns.send_to AND (%(clock)s>=ns.send_from OR %(clock)s<ns.send_to)))
        ORDER BY e.day,e.id LIMIT 20''', params).fetchall()
    sent = 0
    for item in candidates:
        delivery_now = supplied_now.astimezone(auth.MSK) if supplied_now else datetime.now(auth.MSK)
        if not in_window(item, delivery_now):
            continue
        key = (item['id'], item['reminder_version'])
        claim = c.execute('''INSERT INTO calendar_reminders(entry_id,reminder_version,state) VALUES (%s,%s,'sending')
                             ON CONFLICT (entry_id,reminder_version) DO UPDATE SET state='sending',finished_at=NULL
                             WHERE calendar_reminders.state='deferred' RETURNING entry_id''', key).fetchone()
        c.commit()
        if not claim:
            continue
        state = 'deferred'  
        try:
            e = c.execute(ELIGIBLE + ' AND e.id=%(id)s AND e.reminder_version=%(rev)s FOR UPDATE OF e,m,u,ns',
                          {**params, 'tomorrow': delivery_now.date()+timedelta(days=1), 'id': key[0], 'rev': key[1]}).fetchone()
            delivery_now = supplied_now.astimezone(auth.MSK) if supplied_now else datetime.now(auth.MSK)
            if e and in_window(e, delivery_now):
                state = 'uncertain'
                if bot.send(e['chat_id'], reminder_text(e, delivery_now.date())):
                    state = 'sent'
                    sent += 1
        except Exception:
            c.rollback()
            state = 'uncertain'
        c.execute('UPDATE calendar_reminders SET state=%s,finished_at=now() WHERE entry_id=%s AND reminder_version=%s', (state, *key))
        c.commit()
    return sent
