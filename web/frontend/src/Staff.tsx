import { useEffect, useMemo, useRef, useState } from "react";
import { api, http, type Article, type ShopStaff } from "./api";

type WsStaff = { staff: { id: number; name: string; user_id: number | null; user_name: string | null; per_shop: Record<string, number> }[];
  users: { id: number; name: string }[]; can_edit: boolean };
type Preview = { changes: number; same: number; unknown: number; unknown_list: string[]; total: number; staff: string[];
  by_staff: Record<string, number>; clear: number; applied: boolean };

/** Настройки → «Менеджеры»: менеджеры кабинета, кто за какими артикулами магазина; загрузка файлом «артикул → менеджер». */
export function Staff({ shop, onChange }: { shop: number; onChange: () => void }) {
  const [s, setS] = useState<ShopStaff | null>(null);
  const [ws, setWs] = useState<WsStaff | null>(null);
  const [arts, setArts] = useState<Article[]>([]);
  const [err, setErr] = useState(""), [msg, setMsg] = useState("");
  const [q, setQ] = useState("");
  const [only, setOnly] = useState("all");                 // all | none | <id менеджера>
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [to, setTo] = useState("");
  const [add, setAdd] = useState({ name: "", user_id: "" });
  const [pv, setPv] = useState<{ file: File; r: Preview } | null>(null);
  const [busy, setBusy] = useState(false);
  const [others, setOthers] = useState(false);              // менеджеры других магазинов кабинета (обычно не нужны — Example, 22.10)
  const file = useRef<HTMLInputElement>(null);
  const load = () => api.shopStaff(shop).then((x) => {
    setS(x); http.get<WsStaff>(`/api/workspaces/${x.workspace_id}/staff`).then(setWs).catch((e) => setErr(e.message)); onChange();
  }).catch((e) => setErr(e.message));
  useEffect(() => { setS(null); setSel(new Set()); load(); api.articles(shop).then(setArts).catch((e) => setErr(e.message)); }, [shop]); // eslint-disable-line react-hooks/exhaustive-deps
  const name = useMemo(() => Object.fromEntries((s?.staff || []).map((x) => [x.id, x.name])), [s]);
  const list = useMemo(() => arts.filter((a) => {
    const w = s?.assign[a.nm_id];
    if (only === "none" ? w : only !== "all" && w !== Number(only)) return false;
    const ql = q.trim().toLowerCase();
    return !ql || `${a.nm_id} ${a.vendor_code} ${a.title} ${a.subject}`.toLowerCase().includes(ql);
  }), [arts, s, q, only]);
  // менеджеры этого магазина: есть артикулы здесь или пока нигде (новый); остальные — по галочке
  const here = (id: number) => { const x = ws?.staff.find((y) => y.id === id); return !x || others || (x.per_shop[shop] || 0) > 0
    || !Object.values(x.per_shop).some((v) => v > 0); };
  if (err && !s) return <div className="err">{err}</div>;
  if (!s || !ws) return <div className="hint">Загрузка…</div>;
  const done = (m: string) => { setMsg(m); setErr(""); setTimeout(() => setMsg(""), 4000); load(); };
  const fail = (e: Error) => setErr(e.message);
  const assign = (ids: number[], staff_id: number | null) =>
    http.put(`/api/shops/${shop}/staff/assign`, { nm_ids: ids, staff_id }).then(() => { setSel(new Set()); done(`Назначено: ${ids.length} арт.`); }).catch(fail);
  const upload = (f: File, apply: boolean) => {
    setBusy(true); setErr("");
    fetch(`/api/workspaces/${s.workspace_id}/staff/import?name=${encodeURIComponent(f.name)}&apply=${apply}`, { method: "POST", body: f,
      credentials: "same-origin", headers: { "Content-Type": "application/octet-stream" } })
      .then(async (r) => { const j = await r.json(); if (!r.ok) throw new Error(j.detail || r.statusText); return j as Preview; })
      .then((r) => { if (apply) { setPv(null); done(`Загружено из файла: ${r.changes} назначений`); } else setPv({ file: f, r }); })
      .catch(fail).finally(() => setBusy(false));
  };
  const userSel = (v: number | null, on: (x: number | null) => void) => (
    <select value={v ?? ""} disabled={!ws.can_edit} onChange={(e) => on(e.target.value ? Number(e.target.value) : null)}>
      <option value="">— без пользователя —</option>
      {ws.users.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
    </select>);
  const edit = (id: number, name: string, user_id: number | null) => http.put(`/api/staff/${id}`, { name, user_id }).then(() => done("Сохранено")).catch(fail);
  return (
    <div className="board">
      <div className="acc-box">
        <b>Менеджеры кабинета</b>
        <div className="hint">У артикула — один менеджер. Наверху сайта появится выбор «Менеджер»: все вкладки и «Сумма магазинов» считаются по его
          артикулам, внутри можно дальше выбрать категорию или артикул. Менеджер видит весь магазин — фильтр для удобства. Если привязать
          менеджера к пользователю, тот в настройках уведомлений сможет получать утреннюю сводку только по своим артикулам.</div>
        {msg && <div className="ok">{msg}</div>}{err && <div className="err">{err}</div>}
        <table className="board-t staff-t"><thead><tr><th>Менеджер</th><th>Пользователь сервиса</th><th>Артикулов здесь</th><th>Во всех магазинах</th><th></th></tr></thead>
          <tbody>{ws.staff.filter((x) => here(x.id)).map((x) => (
            <tr key={x.id}>
              <td>{ws.can_edit ? <input defaultValue={x.name} onBlur={(e) => e.target.value.trim() !== x.name && edit(x.id, e.target.value, x.user_id)} /> : x.name}</td>
              <td>{userSel(x.user_id, (v) => edit(x.id, x.name, v))}</td>
              <td>{x.per_shop[shop] || 0}</td>
              <td>{Object.values(x.per_shop).reduce((a, b) => a + b, 0)}</td>
              <td>{ws.can_edit && <button className="link" onClick={() => { if (confirm(`Удалить менеджера «${x.name}»? Его артикулы останутся без менеджера.`))
                http.del(`/api/staff/${x.id}`).then(() => done("Удалён")).catch(fail); }}>удалить</button>}</td>
            </tr>))}
          {!ws.staff.length && <tr><td colSpan={5} className="hint">Менеджеров пока нет — добавьте или загрузите файлом.</td></tr>}</tbody></table>
        {ws.staff.some((x) => !here(x.id)) || others ? <label className="chk"><input type="checkbox" checked={others} onChange={(e) => setOthers(e.target.checked)} />
          {" "}показать менеджеров других магазинов кабинета ({ws.staff.filter((x) => (x.per_shop[shop] || 0) === 0 && Object.values(x.per_shop).some((v) => v > 0)).length})</label> : null}
        {ws.can_edit && <div className="board-bar">
          <input placeholder="Имя менеджера" value={add.name} onChange={(e) => setAdd({ ...add, name: e.target.value })} />
          {userSel(add.user_id ? Number(add.user_id) : null, (v) => setAdd({ ...add, user_id: v ? String(v) : "" }))}
          <button disabled={!add.name.trim()} onClick={() => http.post(`/api/workspaces/${s.workspace_id}/staff`,
            { name: add.name, user_id: add.user_id ? Number(add.user_id) : null }).then(() => { setAdd({ name: "", user_id: "" }); done("Добавлен"); }).catch(fail)}>+ Добавить</button>
          <input ref={file} type="file" accept=".xlsx,.csv" hidden onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) upload(f, false); }} />
          <button disabled={busy} onClick={() => file.current?.click()}>⬆ Загрузить файл «артикул → менеджер»</button>
          <span className="hint">столбцы: «Артикул WB» / «SKU» / «Артикул продавца» и «Менеджер»; по всем магазинам кабинета</span>
        </div>}
        {pv && <div className="acc-box staff-pv">
          <b>Файл «{pv.file.name}»: строк {pv.r.total}</b>
          <div>Изменится назначений: <b>{pv.r.changes}</b>{pv.r.same > 0 && <> · уже так: {pv.r.same}</>}{pv.r.clear > 0 && <> · снять менеджера: {pv.r.clear}</>}</div>
          {pv.r.staff.length > 0 && <div>{pv.r.staff.map((n) => `${n}: ${pv.r.by_staff[n]}`).join(" · ")}
            {pv.r.staff.some((n) => !ws.staff.some((x) => x.name.toLowerCase() === n.toLowerCase())) && <span className="hint"> (новые имена будут добавлены)</span>}</div>}
          {pv.r.unknown > 0 && <div className="err">Не нашёл в магазинах: {pv.r.unknown} — {pv.r.unknown_list.join(", ")}{pv.r.unknown > 20 ? "…" : ""}</div>}
          <button className="pri" disabled={busy || !pv.r.changes} onClick={() => upload(pv.file, true)}>Применить</button>
          <button disabled={busy} onClick={() => setPv(null)}>Отмена</button>
        </div>}
      </div>
      <div className="board-bar">
        <input className="q" placeholder="Поиск: артикул, название, предмет" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={only} onChange={(e) => setOnly(e.target.value)}>
          <option value="all">Все артикулы</option><option value="none">Без менеджера</option>
          {s.staff.filter((x) => here(x.id)).map((x) => <option key={x.id} value={x.id}>{x.name} · {x.n}</option>)}
        </select>
        {s.can_edit && s.staff.length > 0 && <>
          <button className="link" onClick={() => setSel(new Set(list.map((a) => a.nm_id)))}>выбрать все по фильтру ({list.length})</button>
          {sel.size > 0 && <>
            <select value={to} onChange={(e) => setTo(e.target.value)}>
              <option value="">— менеджер —</option>{s.staff.filter((x) => here(x.id)).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
              <option value="none">✕ снять менеджера</option></select>
            <button disabled={!to} onClick={() => assign([...sel], to === "none" ? null : Number(to))}>Назначить выбранным ({sel.size})</button>
            <button className="link" onClick={() => setSel(new Set())}>снять выбор</button>
          </>}
        </>}
      </div>
      <div className="board-wrap"><table className="board-t">
        <thead><tr><th></th><th></th><th>Артикул</th><th>Предмет</th><th>Заказов за 30 дн.</th><th>Менеджер</th></tr></thead>
        <tbody>{list.slice(0, 1500).map((a) => (
          <tr key={a.nm_id}>
            <td>{s.can_edit && <input type="checkbox" checked={sel.has(a.nm_id)} onChange={() => setSel((x) => { const n = new Set(x); if (n.has(a.nm_id)) n.delete(a.nm_id); else n.add(a.nm_id); return n; })} />}</td>
            <td>{a.photo && <img src={a.photo} className="thumb" alt="" loading="lazy" />}</td>
            <td><b>{a.vendor_code}</b> <span className="hint">{a.nm_id}</span><div className="hint">{a.title}</div></td>
            <td>{a.subject}</td>
            <td>{a.orders_30d}</td>
            <td>{s.can_edit ? <select value={s.assign[a.nm_id] ?? ""} onChange={(e) => assign([a.nm_id], e.target.value ? Number(e.target.value) : null)}>
              <option value="">—</option>{s.staff.filter((x) => here(x.id)).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
              : name[s.assign[a.nm_id]] || "—"}</td>
          </tr>))}</tbody>
      </table>{list.length > 1500 && <div className="hint">Показаны первые 1 500 — уточните поиск.</div>}</div>
    </div>
  );
}
