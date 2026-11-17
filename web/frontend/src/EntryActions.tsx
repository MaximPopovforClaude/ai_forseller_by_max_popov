import { useEffect, useRef, useState } from "react";
import { http } from "./api";
import { ActionDayContent, DRR, AD_GROUPS, AD_NOTE, AD_ORDER_NOTE, AD_CLASS_NOTE, visibleAct, nf, nf1, type DayRow, type Kind } from "./ActionDayCell";

type Period = { id: string; d_from: string; d_to: string };
type Payload = { days: string[]; kinds: Kind[]; rows: (DayRow & { nm_id: number })[]; demand_note?: string; ad_metrics_note?: string };
const saved = (key: string) => { try { return localStorage.getItem(key) === "1"; } catch { return false; } };

// One bounded request for all visible daily columns; opening a cell never starts collection.
export function useEntryActions(shop: number, nm: string, periods: Period[]) {
  const [show, setShow] = useState(() => saved("entry_actions"));
  const [deep, setDeep] = useState(false);
  const [basis, setBasis] = useState<"limit" | "balance">("limit");
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{ key: string; data?: Payload; error?: string } | null>(null);
  const [opened, setOpened] = useState<{ key: string; day: string } | null>(null);
  const origin = useRef<HTMLButtonElement | null>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const ids = [...new Set(nm.split(",").map(x => x.trim()).filter(Boolean))];
  const sku = ids.length === 1 && /^\d+$/.test(ids[0]) && Number.isSafeInteger(+ids[0]) && +ids[0] > 0 ? +ids[0] : null;
  const days = [...new Set(periods.map(p => p.d_from))].sort();
  const start = days[0], end = days[days.length - 1];
  const reason = !sku ? "Выберите один артикул вверху страницы." : !days.length ? "Сначала загрузите таблицу точек входа." :
    periods.some(p => p.d_from !== p.d_to) ? "Действия доступны по дням. Переключите столбцы на «По дням (30)»." :
    !(Date.parse(end) - Date.parse(start) < 60 * 864e5) ? "Для действий выберите дневные отчёты в пределах 60 дней." : "";
  const enabled = show && !reason;
  const key = enabled ? JSON.stringify([shop, sku, periods, attempt]) : "";
  const data = key && result?.key === key ? result.data : undefined;
  const error = key && result?.key === key ? result.error : undefined;
  const row = data?.rows.find(r => r.nm_id === sku);
  const openDay = enabled && opened?.key === key ? opened.day : null;
  useEffect(() => {
    if (!key) return;
    let live = true;
    const q = new URLSearchParams({ nm_id: String(sku), date_from: start, date_to: end, ad_metrics: "true" });
    http.get<Payload>(`/api/shops/${shop}/manager/day-cells?${q}`).then(data => {
      if (!data.rows.some(r => r.nm_id === sku) || days.some(d => !data.days.includes(d))) throw Error("Даты или артикул действий не совпали с таблицей.");
      if (live) setResult({ key, data });
    }).catch(e => { if (live) setResult({ key, error: e.message }); });
    return () => { live = false; };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (openDay) closeButton.current?.focus(); }, [openDay]);
  const close = () => { setOpened(null); origin.current?.focus(); };
  const controls = <div className="entry-actions-controls">
    <button className="btn" aria-expanded={enabled} disabled={!show && !!reason} onClick={() => {
      setShow(!show); setOpened(null); try { localStorage.setItem("entry_actions", show ? "0" : "1"); } catch { /* optional preference */ }
    }}>{show ? "Скрыть действия" : "Показать действия"}</button>
    {reason && <span className="hint">{reason}</span>}
    {enabled && <span className="hint">Нажмите ячейку над датой: действия, заказы, ДРР и реклама за этот день.</span>}
    {enabled && error && <div role="alert">Действия не загрузились: {error} <button className="btn" onClick={() => setAttempt(x => x + 1)}>Повторить загрузку действий</button></div>}
  </div>;
  const cell = (day: string) => {
    const acts = row?.actions[day] || [];
    const spend = row?.ad_metrics?.[day]?.all;
    const ad = row?.ads?.[day];
    return <button className="entry-action-day btn" disabled={!row} aria-label={`Действия за ${day}`} aria-haspopup="dialog"
      onClick={e => { origin.current = e.currentTarget; setOpened({ key, day }); }}>
      <b>{!row ? error ? "Нет данных действий" : "Загрузка действий…" : `Действия: ${acts.length}`}</b>
      {row && <><span>Заказы: {row.orders[day] == null ? "—" : nf.format(row.orders[day])}</span>
        <span>Реклама: {spend?.spent == null ? "—" : nf.format(spend.spent) + " ₽" + (spend.partial?.includes("spent") ? " *" : "")}
          {ad?.osum && ad.all != null ? ` · ДРР ${nf1.format(ad.all / ad.osum * 100)} %` : ""}</span></>}
    </button>;
  };
  const dialog = openDay && row && data && <div className="modal-shade" onClick={close}>
    <div className="modal entry-actions-dialog" role="dialog" aria-modal="true" aria-labelledby="entry-actions-title"
      onClick={e => e.stopPropagation()} onKeyDown={e => {
        if (e.key === "Escape") { e.stopPropagation(); close(); }
        if (e.key === "Tab") {
          const focus = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('button,select,summary,[tabindex="0"]'));
          const at = focus.indexOf(document.activeElement as HTMLElement);
          if (e.shiftKey && at <= 0) { e.preventDefault(); focus[focus.length - 1]?.focus(); }
          else if (!e.shiftKey && at === focus.length - 1) { e.preventDefault(); focus[0]?.focus(); }
        }
      }}>
      <div className="modal-h"><b id="entry-actions-title">Действия · {openDay.slice(8)}.{openDay.slice(5,7)}.{openDay.slice(0,4)} · WB {sku}</b>
        <button className="x" ref={closeButton} aria-label="Закрыть действия" onClick={close}>✕</button></div>
      <div className="entry-actions-options"><button className="btn" aria-pressed={deep} onClick={() => setDeep(!deep)}>
        {deep ? "Скрыть" : "Показать"} глубокие изменения РК</button>
        <label>Использование бюджета: <select value={basis} onChange={e => setBasis(e.target.value as "limit" | "balance")}>
          <option value="limit">к дневному лимиту</option><option value="balance">расход / (расход + остаток)</option>
        </select></label></div>
      <p className="hint">{AD_CLASS_NOTE}</p>
      <details className="hint"><summary>Как читать показатели</summary>{data.demand_note}<p>ДРР — к сумме заказов статистики WB, как в «Действиях по артикулам». Заказы в ячейке — из воронки. Если суммы заказов нет, вместо ДРР показан расход в рублях.</p><p>{AD_ORDER_NOTE}</p>{AD_NOTE}</details>
      {data.ad_metrics_note && <p className="hint">{data.ad_metrics_note}</p>}
      <div className="entry-actions-content"><b>Заказы и показатели дня</b>
        <ActionDayContent row={row} day={openDay} kinds={Object.fromEntries(data.kinds.map(k => [k.key, k]))}
          drr={DRR.map(([k]) => k)} deepAds={deep} dayPrices adStats adGroups={AD_GROUPS.map(([k]) => k)} adBasis={basis} />
        {!(row.actions[openDay] || []).filter(a => visibleAct(a, deep)).length && <p className="hint">Нет сохранённых действий для выбранного отображения.</p>}
      </div>
    </div>
  </div>;
  return { enabled, controls, cell, dialog };
}
