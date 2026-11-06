import { useEffect, useRef, useState } from 'react';
import { http } from './api';
import type { Workspace } from './api';
import './Calendar.css';

type Entry = { id: number; kind: 'task' | 'note'; title: string; description: string; day: string;
  shop_id: number | null; shop: string | null; assignee_id: number | null; assignee: string | null;
  author: string; status: 'open' | 'done' | 'cancelled'; version: number; can_edit: boolean; reminder_state: string | null };
type Person = { id: number; name: string; shop_ids: number[] | null };
type Result = { items: Entry[]; today: string; me: number; members: Person[]; shops: { id: number; title: string }[];
  can_add: boolean; stometric_connected: boolean; truncated: boolean; action_counts: { day: string; n: number }[] };
type Action = { id: string; source: string; title: string; description: string; nm_id: number; shop: string; shop_id: number };
type Draft = Pick<Entry, 'kind' | 'title' | 'description' | 'day' | 'shop_id' | 'assignee_id' | 'status'>;
const states = { open: 'Открыта', done: 'Выполнена', cancelled: 'Отменена' };
export const mskDay = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Moscow', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
const label = (day: string) => new Date(day + 'T12:00:00Z').toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' });
const iso = (d: Date) => d.toISOString().slice(0, 10);
export function monthDays(month: string) {
  const [y, m] = month.split('-').map(Number);
  const first = new Date(Date.UTC(y, m - 1, 1));
  first.setUTCDate(first.getUTCDate() - (first.getUTCDay() + 6) % 7);
  return Array.from({ length: 42 }, (_, i) => iso(new Date(first.getTime() + i * 86400000)));
}
const shiftMonth = (month: string, n: number) => { const [y, m] = month.split('-').map(Number); return iso(new Date(Date.UTC(y, m - 1 + n, 1))).slice(0, 7); };

// An old response must never replace another account, month or day's data.
function useResource<T>(url: string | null) {
  const [value, setValue] = useState<{ url: string; data?: T; error?: string } | null>(null);
  const [revision, setRevision] = useState(0);
  const sequence = useRef(0);
  useEffect(() => {
    if (!url) return;
    let active = true;
    const load = () => {
      const seq = ++sequence.current;
      http.get<T>(url).then(data => { if (active && seq === sequence.current) setValue({ url, data }); })
        .catch(e => { if (active && seq === sequence.current) setValue({ url, error: (e as Error).message }); });
    };
    load();
    const timer = window.setInterval(load, 60000);
    const focus = () => { if (document.visibilityState === 'visible') load(); };
    document.addEventListener('visibilitychange', focus);
    return () => { active = false; sequence.current++; window.clearInterval(timer); document.removeEventListener('visibilitychange', focus); };
  }, [url, revision]);
  return { data: value?.url === url ? value.data : undefined, error: value?.url === url ? value.error : undefined,
    reload: () => setRevision(x => x + 1) };
}

function EntryCard({ e, today, onEdit }: { e: Entry; today: string; onEdit?: (e: Entry) => void }) {
  const overdue = e.kind === 'task' && e.status === 'open' && e.day < today;
  return <article className={'cal-entry ' + e.kind + (e.status !== 'open' ? ' closed' : '')}>
    <div className="cal-entry-head"><b>{e.kind === 'task' ? '☐ ' : '✎ '}{e.title}</b>
      <span className={overdue ? 'cal-overdue' : 'hint'}>{overdue ? 'Просрочена · ' : ''}{states[e.status]}</span></div>
    {e.description && <p className="cal-description">{e.description}</p>}
    <div className="hint">{e.kind === 'task' ? `Срок: ${label(e.day)} · Исполнитель: ${e.assignee}` : label(e.day)}
      {' · '}{e.shop || 'Весь аккаунт'} · Автор: {e.author}</div>
    {(e.reminder_state === 'uncertain' || e.reminder_state === 'sending') && <div className="hint">Доставка напоминания не подтверждена. Задача остаётся на Главной.</div>}
    {onEdit && e.can_edit && <button className="link" onClick={() => onEdit(e)}>Изменить / отметить выполнение</button>}
  </article>;
}

export function Calendar({ wsId, workspaces, initialDay }: { wsId: number; workspaces: Workspace[]; initialDay?: string }) {
  const [selectedWs, setSelectedWs] = useState(wsId);
  return <section className="calendar-page">
    <div className="cal-toolbar"><h2>Календарь</h2>
      <label>Аккаунт <select value={selectedWs} onChange={e => setSelectedWs(Number(e.target.value))}>
        {workspaces.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
      </select></label></div>
    <CalendarMonth key={selectedWs} wsId={selectedWs} initialDay={initialDay} />
  </section>;
}

function CalendarMonth({ wsId, initialDay }: { wsId: number; initialDay?: string }) {
  const [day, setDay] = useState(initialDay || mskDay());
  const [month, setMonth] = useState(day.slice(0, 7));
  const [shop, setShop] = useState('');
  const [mine, setMine] = useState(false);
  const [closed, setClosed] = useState(false);
  const [actions, setActions] = useState(() => { try { return localStorage.getItem(`calendar-actions:${wsId}`) === '1'; } catch { return false; } });
  const [editing, setEditing] = useState<Entry | 'task' | 'note' | null>(null);
  const days = monthDays(month);
  const { data: r, error, reload } = useResource<Result>(`/api/workspaces/${wsId}/calendar?start=${days[0]}&end=${days[41]}&closed=${closed}&mine=${mine}&actions=${actions}${shop ? `&shop=${shop}` : ''}`);
  const move = (next: string) => { setMonth(next); setDay(next + '-01'); setEditing(null); };
  const choose = (d: string) => { setDay(d); setEditing(null); };
  return <>
    <p className="hint">Общий календарь команды. Задачи и заметки магазина видны только сотрудникам с доступом к нему.
      Задачи исполнителя появляются на Главной за день до срока и остаются до выполнения. Даты — по Москве.</p>
    <div className="cal-toolbar">
      <button aria-label="Предыдущий месяц" onClick={() => move(shiftMonth(month, -1))}>←</button>
      <label>Месяц <input type="month" value={month} onChange={e => { if (/^\d{4}-\d{2}$/.test(e.target.value)) move(e.target.value); }} /></label>
      <button aria-label="Следующий месяц" onClick={() => move(shiftMonth(month, 1))}>→</button>
      <button onClick={() => { const d = r?.today || mskDay(); setMonth(d.slice(0, 7)); choose(d); }}>Сегодня</button>
      <label>Магазин <select value={shop} onChange={e => { setShop(e.target.value); setEditing(null); }}>
        <option value="">Все доступные</option>{r?.shops.map(s => <option key={s.id} value={s.id}>{s.title}</option>)}
      </select></label>
      <label><input type="checkbox" checked={mine} onChange={e => setMine(e.target.checked)} /> Мои: назначенные мне и созданные мной</label>
      <label><input type="checkbox" checked={closed} onChange={e => setClosed(e.target.checked)} /> Выполненные и отменённые</label>
      <label><input type="checkbox" checked={actions} onChange={e => { setActions(e.target.checked); try { localStorage.setItem(`calendar-actions:${wsId}`, e.target.checked ? '1' : '0'); } catch { /* unavailable storage */ } }} /> Действия по артикулам</label>
    </div>
    {error && <div className="err" role="alert">Не удалось загрузить календарь: {error} <button onClick={reload}>Повторить</button></div>}
    {!r && !error && <p role="status">Загружаю календарь…</p>}
    {r && <>
      {!r.stometric_connected && <p className="disclaimer">Чтобы получать напоминания в Стометрике, подключите его в «Настройки аккаунта → Уведомления» и нажмите /start в боте. Задачи на Главной доступны и без Telegram.</p>}
      {!r.can_add && <p className="hint">У вас доступ для просмотра. Ставить задачи, делать заметки и отмечать выполнение могут редакторы и администраторы.</p>}
      {r.truncated && <p className="disclaimer">Показаны первые 2000 записей. Уточните магазин или включите «Мои».</p>}
      <div className="cal-grid" role="group" aria-label="Дни календаря">
        {['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map(x => <div className="cal-weekday" key={x}>{x}</div>)}
        {days.map(d => {
          const items = r.items.filter(e => e.day === d), n = r.action_counts.find(x => x.day === d)?.n || 0;
          return <button type="button" key={d} aria-label={label(d)} aria-pressed={d === day}
            className={'cal-day' + (d === day ? ' selected' : '') + (d === r.today ? ' today' : '') + (!d.startsWith(month) ? ' outside' : '')}
            onClick={() => choose(d)}>
            <b>{Number(d.slice(8))}</b>
            {items.slice(0, 3).map(e => <span key={e.id} className={'cal-mini ' + e.kind + (e.status !== 'open' ? ' closed' : '')} title={e.title}>{e.kind === 'task' ? '☐ ' : '✎ '}{e.title}</span>)}
            {items.length > 3 && <small>Ещё {items.length - 3}</small>}{actions && n > 0 && <small className="cal-actions-count">Действий: {n}</small>}
          </button>;
        })}
      </div>
      <div className="cal-toolbar"><h3>{label(day)}</h3>{r.can_add && <>
        <button onClick={() => setEditing('task')}>+ Задача</button><button onClick={() => setEditing('note')}>+ Заметка</button></>}</div>
      {editing && <EntryEditor key={typeof editing === 'string' ? editing + day : editing.id} wsId={wsId} entry={editing} day={day} shop={shop} data={r}
        onCancel={() => setEditing(null)} onSaved={() => { setEditing(null); reload(); }} />}
      <div className="cal-agenda">{r.items.filter(e => e.day === day).map(e => <EntryCard key={e.id} e={e} today={r.today} onEdit={setEditing} />)}
        {!r.items.some(e => e.day === day) && <p className="hint">На этот день задач и заметок пока нет.</p>}</div>
      {actions && <ActionDay key={`${day}:${shop}`} wsId={wsId} day={day} shop={shop} />}
    </>}
  </>;
}

function EntryEditor({ wsId, entry, day, shop, data, onCancel, onSaved }: { wsId: number; entry: Entry | 'task' | 'note'; day: string; shop: string;
  data: Result; onCancel: () => void; onSaved: () => void }) {
  const existing = typeof entry !== 'string' ? entry : null;
  const [draft, setDraft] = useState<Draft>(existing || { kind: entry as 'task' | 'note', title: '', description: '', day, shop_id: shop ? Number(shop) : null,
    assignee_id: entry === 'task' ? (data.members.some(m => m.id === data.me) ? data.me : null) : null, status: 'open' });
  const [key] = useState(() => crypto.randomUUID());
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const live = useRef(true);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  const field = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft(d => ({ ...d, [k]: v }));
  const people = data.members.filter(m => draft.shop_id === null || m.shop_ids === null || m.shop_ids.includes(draft.shop_id));
  const save = async (e: React.FormEvent) => {
    e.preventDefault(); if (busy) return; setBusy(true); setError('');
    const body = { kind: draft.kind, title: draft.title, description: draft.description, day: draft.day, shop_id: draft.shop_id, assignee_id: draft.assignee_id };
    try {
      if (existing) await http.put(`/api/workspaces/${wsId}/calendar/${existing.id}`, { ...body, version: existing.version, status: draft.status });
      else await http.post(`/api/workspaces/${wsId}/calendar`, { ...body, request_key: key });
      if (live.current) onSaved();
    } catch (err) { if (live.current) setError((err as Error).message); }
    finally { if (live.current) setBusy(false); }
  };
  return <form className="cal-editor" onSubmit={save}>
    <h3>{existing ? 'Изменить' : 'Добавить'} {draft.kind === 'task' ? 'задачу' : 'заметку'}</h3>
    <fieldset disabled={busy}>
      <label>Название <input required maxLength={200} value={draft.title} onChange={e => field('title', e.target.value)} autoFocus /></label>
      <label>Описание <textarea maxLength={4000} rows={3} value={draft.description} onChange={e => field('description', e.target.value)} /></label>
      <div className="cal-toolbar"><label>{draft.kind === 'task' ? 'Срок' : 'Дата'} <input required type="date" value={draft.day} onChange={e => field('day', e.target.value)} /></label>
        <label>Магазин <select value={draft.shop_id || ''} onChange={e => {
          const id = e.target.value ? Number(e.target.value) : null;
          setDraft(d => ({ ...d, shop_id: id, assignee_id: data.members.some(m => m.id === d.assignee_id && (id === null || m.shop_ids === null || m.shop_ids.includes(id))) ? d.assignee_id : null }));
        }}><option value="">Весь аккаунт</option>{data.shops.map(s => <option key={s.id} value={s.id}>{s.title}</option>)}</select></label>
        {draft.kind === 'task' && <label>Исполнитель <select required value={draft.assignee_id || ''} onChange={e => field('assignee_id', e.target.value ? Number(e.target.value) : null)}>
          <option value="">Выберите сотрудника</option>
          {existing?.assignee_id && !people.some(m => m.id === existing.assignee_id) && <option value={existing.assignee_id}>{existing.assignee} (доступ изменён)</option>}
          {people.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label>}
        {existing && <label>Статус <select value={draft.status} onChange={e => field('status', e.target.value as Draft['status'])}>
          <option value="open">Открыта</option>{draft.kind === 'task' && <option value="done">Выполнена</option>}<option value="cancelled">Отменена</option></select></label>}
      </div>
      {error && <p className="err" role="alert">{error}</p>}
      <div className="cal-toolbar"><button type="submit">{busy ? 'Сохраняю…' : 'Сохранить'}</button><button type="button" onClick={onCancel}>Закрыть</button></div>
    </fieldset>
  </form>;
}

function ActionDay({ wsId, day, shop }: { wsId: number; day: string; shop: string }) {
  const [offset, setOffset] = useState(0);
  const { data, error, reload } = useResource<{ items: Action[]; more: boolean }>(`/api/workspaces/${wsId}/calendar/actions?day=${day}&offset=${offset}${shop ? `&shop=${shop}` : ''}`);
  return <section className="cal-source"><h4>Действия по артикулам</h4><p className="hint">Записи из листа и журнала изменений. Изменить ручную запись можно в «Действия по артикулам». Эти записи сами по себе не создают напоминания.</p>
    {error && <div className="err">{error} <button onClick={reload}>Повторить</button></div>}
    {!data && !error && <p>Загружаю действия…</p>}
    {data?.items.map(a => <article className="cal-entry action" key={`${a.source}:${a.shop_id}:${a.nm_id}:${a.id}`}>
      <b>{a.title}</b><div className="hint">{a.shop} · Артикул {a.nm_id} · {a.source === 'manual' ? 'Запись сотрудника' : 'Автоматическая запись'}</div>
      {a.description && <p className="cal-description">{a.description}</p>}</article>)}
    {data && !data.items.length && <p className="hint">Действий за выбранный день нет.</p>}
    <div className="cal-toolbar">{offset > 0 && <button onClick={() => setOffset(x => Math.max(0, x - 200))}>← Предыдущие</button>}
      {data?.more && <button onClick={() => setOffset(x => x + 200)}>Следующие 200 →</button>}</div>
  </section>;
}

export function HomeCalendar({ wsId, onOpen }: { wsId: number; onOpen: (day: string) => void }) {
  const { data, error, reload } = useResource<{ items: Entry[]; today: string; truncated: boolean }>(`/api/workspaces/${wsId}/calendar/due`);
  if (error) return <div className="err">Не удалось проверить сроки календаря. <button onClick={reload}>Повторить</button></div>;
  if (!data?.items.length) return null;
  return <section className="cal-home"><div className="cal-toolbar"><b>📅 Мои задачи: завтра, сегодня и просроченные ({data.items.length}{data.truncated ? '+' : ''})</b>
    <button className="link" onClick={() => onOpen(data.today)}>Открыть календарь</button></div>
    {data.items.slice(0, 8).map(e => <div key={e.id}><EntryCard e={e} today={data.today} />
      <button className="link" onClick={() => onOpen(e.day)}>Открыть день и отметить выполнение</button></div>)}
    {data.items.length > 8 && <p className="hint">Остальные задачи доступны в календаре.</p>}
  </section>;
}
