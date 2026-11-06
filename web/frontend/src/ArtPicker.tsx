import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Article } from "./api";

/** Выбор артикулов: поле (можно вписать номера через запятую) + выпадающий список с фото, поиском и галочками. */
export function ArtPicker({ shop, value, onChange, only }: { shop: number; value: string; onChange: (v: string) => void; only?: Set<number> | null }) {
  const [arts, setArts] = useState<Article[]>([]);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const box = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {          // сменили магазин — старый список сразу убираем, опоздавший ответ прежнего магазина игнорируем
    let live = true;
    setArts([]); setLoading(true);
    api.articles(shop).then((a) => { if (live) setArts(a); }).catch(() => { if (live) setArts([]); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [shop]);
  useEffect(() => {
    const h = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const sel = useMemo(() => value.split(/[\s,;]+/).filter((x) => /^\d+$/.test(x)).map(Number), [value]);
  const ql = q.trim().toLowerCase();
  const list = useMemo(() => arts.filter((a) => (!only || only.has(a.nm_id)) && (!ql || String(a.nm_id).includes(ql) || (a.vendor_code || "").toLowerCase().includes(ql)
    || (a.title || "").toLowerCase().includes(ql) || (a.subject || "").toLowerCase().includes(ql))), [arts, ql, only]);
  // группы: предметы (категории) и свои склейки; клик — отметить все артикулы группы (повторный клик — снять)
  const groups = useMemo(() => {
    const m = new Map<string, { kind: "subj" | "grp"; name: string; ids: number[] }>();
    for (const a of arts) {
      if (only && !only.has(a.nm_id)) continue;      // выбран менеджер — группы из его артикулов
      for (const [kind, name] of [["subj", a.subject], ["grp", a.grp]] as const) {
        if (!name) continue;
        const k = kind + ":" + name;
        if (!m.has(k)) m.set(k, { kind, name, ids: [] });
        m.get(k)!.ids.push(a.nm_id);
      }
    }
    return [...m.values()].sort((x, y) => (x.kind === y.kind ? y.ids.length - x.ids.length : x.kind === "subj" ? -1 : 1));
  }, [arts, only]);
  const flipGroup = (ids: number[]) => {
    const all = ids.every((i) => sel.includes(i));
    onChange((all ? sel.filter((x) => !ids.includes(x)) : [...new Set([...sel, ...ids])]).join(","));
  };
  const toggle = (id: number) => onChange((sel.includes(id) ? sel.filter((x) => x !== id) : [...sel, id]).join(","));
  const label = sel.length === 0 ? (only ? "Все артикулы менеджера" : "Все артикулы") : sel.length === 1
    ? (arts.find((a) => a.nm_id === sel[0])?.vendor_code || String(sel[0])) : `Выбрано: ${sel.length}`;
  return (
    <div className="ap" ref={box}>
      <button className="ap-btn" onClick={() => setOpen(!open)} title="Выбрать артикулы из списка">
        {sel.length === 1 && arts.find((a) => a.nm_id === sel[0])?.photo && <img src={arts.find((a) => a.nm_id === sel[0])!.photo!} alt="" />}
        <span>{label}</span> ▾
      </button>
      {open && (
        <div className="ap-pop">
          <div className="ap-bar">
            <input autoFocus placeholder="Поиск: артикул, название, предмет…" value={q} onChange={(e) => setQ(e.target.value)} />
            <button onClick={() => onChange("")}>Все</button>
          </div>
          {groups.length > 0 && <div className="ap-groups">
            {groups.map((g) => {
              const n = g.ids.filter((i) => sel.includes(i)).length;
              return <button key={g.kind + g.name} className={"ap-g" + (n === g.ids.length ? " on" : n ? " part" : "") + (g.kind === "grp" ? " own" : "")}
                title={(g.kind === "subj" ? "Предмет" : "Склейка") + ": отметить все артикулы группы, повторно — снять"} onClick={() => flipGroup(g.ids)}>
                {g.kind === "grp" ? "🔗 " : ""}{g.name} <span>{n ? `${n}/` : ""}{g.ids.length}</span></button>;
            })}
          </div>}
          <div className="ap-list">
            {list.map((a) => (
              <label key={a.nm_id} className={"ap-row" + (sel.includes(a.nm_id) ? " on" : "")}>
                <input type="checkbox" checked={sel.includes(a.nm_id)} onChange={() => toggle(a.nm_id)} />
                {a.photo ? <img src={a.photo} alt="" loading="lazy" /> : <span className="ap-nophoto" />}
                <span className="ap-txt">
                  <b>{a.vendor_code || a.nm_id}</b> <span className="hint">{a.nm_id}</span>
                  <span className="ap-t">{a.title}</span>
                </span>
                <span className="ap-n" title="Заказов за 30 дней">{a.orders_30d}</span>
              </label>
            ))}
            {!list.length && <div className="hint">{loading ? "Загружаю артикулы магазина…" : "Ничего не найдено"}</div>}
          </div>
          <div className="hint ap-foot">Отсортировано по заказам за 30 дней. Можно отметить несколько.</div>
        </div>
      )}
      <input className="nm" placeholder="или номера через запятую" value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}
