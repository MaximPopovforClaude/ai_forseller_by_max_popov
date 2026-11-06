import { useEffect, useMemo, useState } from "react";
import { api, http } from "./api";

/** РНП — «рука на пульсе» (Version2 WB, по видео «Системы 10X»): итог кабинета и блок по каждому артикулу,
 *  4 показателя × 2 строки, план/прогноз/факт месяца, мини-графики 30 дней прямо в строке, недели, дни месяца с цветом плана. */

type V = Record<string, number | null>;
type Spark = Record<string, (number | null)[]>;
type Block = { nm_id: number; vendor_code: string | null; title: string | null; brand: string | null; subject: string | null; photo: string | null;
  price: number | null; price_spp: number | null; buyout: number; buyout_own: boolean; loc: number | null; stock: number; fbs?: number; days_fbs?: number | null;
  days_left: number | null; days_left0: number | null; month: V; forecast: V; plan: V | null; plan_day: V | null; weeks: V[];
  days: Record<string, V>; spark: Spark; bp_weeks: number[] | null };
type Total = Omit<Block, "nm_id" | "vendor_code" | "title" | "brand" | "subject" | "photo" | "price" | "price_spp" | "buyout" | "buyout_own" | "bp_weeks"> & { articles: number };
type Data = { error?: string; month: string; days: string[]; weeks: [string, string][]; current: boolean; elapsed: number; dim: number;
  total: Total; blocks: Block[]; count: number; offset: number; page: number; has_plan: boolean; sorts: Record<string, string>;
  brands: string[]; subjects: string[]; buyout_shop: number; mp?: string; stale?: boolean; bonus?: boolean; cached_at?: string; tax_basis?: string };

// строки блока: [ключ значения, подпись группы, подпись строки, формат, «меньше — лучше», ключ графика, цвет графика]
const ROWS: [string, string, string, "money" | "int" | "pct", boolean, string, string][] = [
  ["orders_sum", "Заказы", "Сумма, р", "money", false, "orders_sum", "#2f3fd8"], ["orders", "Заказы", "Кол-во", "int", false, "", ""],
  ["buyouts_sum", "Выкупы", "Сумма, р", "money", false, "buyouts_sum", "#f5a524"], ["buyouts", "Выкупы", "Кол-во", "int", false, "", ""],
  ["ads", "Рекламный бюджет", "Сумма, р", "money", true, "drr", "#dc2626"], ["drr", "Рекламный бюджет", "ДРР", "pct", true, "", ""],
  ["profit", "Прибыль расчет", "Сумма, р", "money", false, "profit", "#16a34a"], ["margin", "Прибыль расчет", "Маржа с ДРР", "pct", false, "", ""],
];
// промобонусы (Кэшбэк) — строки, только если в магазине реклама оплачивается и бонусами 
const BONUS_ROWS: typeof ROWS = [
  ["bonus", "Реклама бонусами", "Сумма, р", "money", true, "", ""], ["drr_bonus", "Реклама бонусами", "ДРР", "pct", true, "", ""],
  ["ads_all", "Реклама всего", "Деньги + бонусы", "money", true, "", ""], ["drr_all", "Реклама всего", "ДРР", "pct", true, "", ""],
];
const GROUP_COLOR: Record<string, string> = { "Заказы": "#2f3fd8", "Выкупы": "#d97706", "Рекламный бюджет": "#dc2626", "Прибыль расчет": "#16a34a",
  "Реклама бонусами": "#9333ea", "Реклама всего": "#b91c1c" };
const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const f = (v: number | null | undefined, t: string) => v == null || !Number.isFinite(v) ? "" : t === "pct" ? (v * 100).toFixed(2).replace(".", ",") + "%" : nf.format(v);
const MON = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
const dd = (s: string) => `${s.slice(8, 10)}.${s.slice(5, 7)}`;

/** Мини-график в строке (как SPARKLINE в таблице): столбики или линия; минус — красным. */
function Spark({ vals, color, kind = "bar", w = 128, h = 40 }: { vals: (number | null)[]; color: string; kind?: "bar" | "line"; w?: number; h?: number }) {
  const xs = vals.map((v) => (v == null || !Number.isFinite(v) ? null : v));
  const nums = xs.filter((v): v is number => v != null);
  if (!nums.length) return <svg width={w} height={h} />;
  const hi = Math.max(0, ...nums), lo = Math.min(0, ...nums);
  const rng = hi - lo || 1;
  const y = (v: number) => h - 2 - ((v - lo) / rng) * (h - 4);
  const step = w / xs.length;
  if (kind === "line") {
    const lo2 = Math.min(...nums), hi2 = Math.max(...nums), r2 = hi2 - lo2 || 1;
    const pts = xs.map((v, i) => (v == null ? null : `${(i + 0.5) * step},${h - 3 - ((v - lo2) / r2) * (h - 6)}`)).filter(Boolean).join(" ");
    return <svg width={w} height={h} className="rnp-spark"><polyline points={pts} fill="none" stroke={color} strokeWidth={1.4} /></svg>;
  }
  return <svg width={w} height={h} className="rnp-spark">
    {xs.map((v, i) => v == null || v === 0 ? null :
      <rect key={i} x={i * step + 0.5} width={Math.max(1, step - 1)} y={Math.min(y(v), y(0))} height={Math.max(1, Math.abs(y(v) - y(0)))}
        fill={v < 0 ? "#dc2626" : color} />)}
  </svg>;
}

const zone = (v: number | null | undefined, good: number, mid: number) =>
  v == null ? "" : v >= good ? "z-good" : v >= mid ? "z-mid" : "z-bad";

export function Rnp({ shop, hideChg = false, nm = "", staff = null }: { shop: number; hideChg?: boolean; nm?: string; staff?: number | null }) {
  const now = new Date();
  const [groups, setGroups] = useState<{ key: string; title: string }[]>([]);
  useEffect(() => { api.groups(shop).then(setGroups).catch(() => setGroups([])); }, [shop]);
  const [month, setMonth] = useState(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`);
  const [sort, setSort] = useState("orders_sum");
  const [brand, setBrand] = useState(""); const [subject, setSubject] = useState(""); const [group, setGroup] = useState("");
  const [withBuyout, setWithBuyout] = useState(true);
  const [showDays, setShowDays] = useState(false);
  const [showLeft, setShowLeft] = useState(true);    // графики слева — по умолчанию включены 
  const [data, setData] = useState<Data | null>(null);
  const [more, setMore] = useState<Block[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const q = (off: number) => `/api/shops/${shop}/rnp?month=${month}&sort=${sort}&offset=${off}&brand=${encodeURIComponent(brand)}` +
    `&subject=${encodeURIComponent(subject)}&group=${encodeURIComponent(group)}` +
    (nm.trim() ? `&nm_ids=${nm.replace(/\s+/g, "")}` : "") + (staff ? `&staff=${staff}` : "");   // артикулы и менеджер — из шапки
  useEffect(() => {
    let live = true;
    setBusy(true); setErr(""); setMore([]);
    http.get<Data>(q(0)).then((d) => { if (live) { setData(d); if (d.error) setErr(d.error); } })
      .catch((e) => live && setErr(e.message)).finally(() => live && setBusy(false));
    return () => { live = false; };
  }, [shop, month, sort, brand, subject, group, nm, staff]);   // eslint-disable-line react-hooks/exhaustive-deps
  const blocks = useMemo(() => [...(data?.blocks || []), ...more], [data, more]);
  const loadMore = () => {
    if (!data) return;
    setBusy(true);
    http.get<Data>(q(blocks.length)).then((d) => setMore((m) => [...m, ...(d.blocks || [])])).catch((e) => setErr(e.message)).finally(() => setBusy(false));
  };
  const months = useMemo(() => {
    const out: string[] = [];
    for (let i = 0; i < 13; i++) { const d = new Date(now.getFullYear(), now.getMonth() - i, 1); out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`); }
    return out;
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  const days = [...(data?.days || [])].reverse();   // свежий день слева 
  const head = (
    <tr>
      <th className="rnp-sticky0">Фото</th><th className="rnp-sticky1">Карточка</th>
      <th colSpan={2}>Показатели актуальные</th>
      {showLeft && <th>Графики 30Д</th>}
      <th colSpan={2} className="rnp-month">{MON[Number(month.slice(5, 7)) - 1]} {month.slice(0, 4)}</th>
      <th>План день</th><th>План мес.</th><th colSpan={2}>Прогноз мес.</th><th>Факт мес.</th><th>Графики 30Д</th>
      <th title={data ? `${dd(data.weeks[0][0])}–${dd(data.weeks[0][1])}` : ""}>3 Нед</th>
      <th title={data ? `${dd(data.weeks[1][0])}–${dd(data.weeks[1][1])}` : ""}>2 Нед</th>
      <th title={data ? `${dd(data.weeks[2][0])}–${dd(data.weeks[2][1])}` : ""}>1 Нед</th>{!hideChg && <th>Дин. Нед.</th>}
      {showDays && days.map((d) => <th key={d}>{dd(d)}</th>)}
    </tr>
  );

  const ym = !!data?.mp && data.mp !== "wb";      // Маркет и Ozon: без СПП
  const MAIN = data?.mp === "ym" ? "FBY" : "FBO", MAIN_T = data?.mp === "ym" ? "склады Маркета" : data?.mp === "ozon" ? "склады Ozon" : "склады WB";
  const block = (b: Block | Total, isTotal: boolean) => {
    const bb = b as Block;
    const left: [string, React.ReactNode, string, number][] = [   // [подпись, значение, класс, строк]
      [isTotal ? "Общий % локальных заказов" : "Локализация", f(b.loc, "pct"), zone(b.loc, 0.7, 0.5), 2],
      ["Остатки", b.fbs ? <div className="rnp-stk" title={`${MAIN} — ${MAIN_T}, FBS — свои склады (последний снимок)`}>
        <span>{MAIN} {nf.format(b.stock || 0)}</span><span>FBS {nf.format(b.fbs)}</span><b>Всего {nf.format((b.stock || 0) + b.fbs)}</b></div>
        : nf.format(b.stock || 0), "", 1],
      ["Хватит на", b.fbs ? <div className="rnp-stk" title={`Дней при текущей скорости заказов (за 30 дней): ${MAIN} — ${MAIN_T}, FBS — свои склады`}>
        <span>{MAIN} {(withBuyout ? b.days_left : b.days_left0) ?? "—"} дн.</span><span>FBS {b.days_fbs ?? "—"} дн.</span>
        <b>Всего {b.days_fbs != null && (withBuyout ? b.days_left : b.days_left0) != null ? (withBuyout ? b.days_left! : b.days_left0!) + b.days_fbs : "—"} дн.</b></div>
        : (withBuyout ? b.days_left : b.days_left0) ?? "",
        zone(b.fbs ? ((withBuyout ? b.days_left : b.days_left0) ?? 0) + (b.days_fbs ?? 0) : (withBuyout ? b.days_left : b.days_left0), 14, 7), 1],
      ["КЭМ", f(b.month.krrr, "pct"), zone(b.month.krrr, 0.7, 0.5), 2],
      ["Маржа до ДРР", f(b.month.margin_pre, "pct"), "", 1], ["Маржа с ДРР", f(b.month.margin, "pct"), "", 1],
    ];
    const rows = data?.bonus ? [...ROWS, ...BONUS_ROWS] : ROWS;
    left[5][3] += rows.length - ROWS.length;          // последняя ячейка слева тянется на строки бонусов
    const leftAt: Record<number, number> = { 0: 0, 2: 1, 3: 2, 4: 3, 6: 4, 7: 5 };
    const lsp: [number, React.ReactNode][] = isTotal
      ? [[0, <Spark key="l" vals={(b.spark.loc || [])} color="#7c3aed" kind="line" />]]
      : [[0, <Spark key="p" vals={b.spark.price_spp || []} color="#7c3aed" kind="line" />],
         [2, <Spark key="b" vals={bb.bp_weeks || []} color="#d97706" kind="line" h={40} />],
         [4, <Spark key="k" vals={b.spark.krrr || []} color="#16a34a" kind="line" />],
         [6, <Spark key="m" vals={b.spark.margin_pre || []} color="#0891b2" kind="line" />]];
    const lspLabel = isTotal ? ["Локализация"] : [ym ? "Средняя цена заказа" : "Цена с СПП", "% выкупа (нед.)", "КЭМ", "Маржа до ДРР"];
    return rows.map(([key, grp, sub, fmt, lessBetter, spk, col], i) => {
      const pd = b.plan_day?.[key], pm = b.plan?.[key], fc = b.forecast[key], fact = b.month[key];
      const pct = pm != null && fc != null && pm !== 0 && fmt !== "pct" ? fc / pm : null;
      const pctCls = pct == null ? "" : (lessBetter ? pct <= 1 : pct >= 1) ? "t-good" : "t-bad";
      const w = b.weeks.map((x) => x[key]);
      const dyn = w[2] != null && w[1] != null ? (w[2] as number) - (w[1] as number) : null;
      const dynCls = !dyn ? "" : (lessBetter ? dyn < 0 : dyn > 0) ? "t-good" : "t-bad";
      const li = leftAt[i];
      return (
        <tr key={key} className={(i === 0 ? "rnp-first " : "") + (i % 2 ? "rnp-sub" : "")}>
          {i === 0 && <td rowSpan={rows.length} className="rnp-sticky0 rnp-photo">
            {isTotal ? <div className="rnp-total-l">ИТОГО<br /><small>{(b as Total).articles} арт.</small></div>
              : bb.photo ? <img src={bb.photo} alt="" loading="lazy" /> : null}</td>}
          {i === 0 && <td rowSpan={rows.length} className="rnp-sticky1 rnp-card">
            {isTotal ? <div className="rnp-hint">Прибыль расчётная = заказы × % выкупа × юнит-экономика (не факт выкупов)
              {data?.tax_basis && <p>{data.tax_basis}</p>}
            </div> : <>
              <b>{bb.nm_id}</b>
              {bb.price != null && <div>р.{nf.format(bb.price)} <small>{ym ? "цена" : "до СПП"}</small></div>}
              {bb.price_spp != null && <div>р.{nf.format(bb.price_spp)} <small>{ym ? "в заказах" : "с СПП"}</small></div>}
              <div className="rnp-title" title={bb.title || ""}>{bb.title}</div>
              <div className="rnp-vc">{bb.vendor_code}</div>
              <small title={bb.buyout_own ? "по отчёту реализации за 4 недели" : "у артикула мало выкупов — общий % кабинета"}>
                выкуп {f(bb.buyout, "pct")}{bb.buyout_own ? "" : "*"}</small>
            </>}</td>}
          {li !== undefined && <><td rowSpan={left[li][3]} className="rnp-lab">{left[li][0]}</td>
            <td rowSpan={left[li][3]} className={"rnp-val " + left[li][2]}>{left[li][1]}</td></>}
          {showLeft && (i % 2 === 0) && <td rowSpan={2} className="rnp-sp">
            {lsp.find(([k]) => k === i)?.[1] ?? null}
            {lsp.find(([k]) => k === i) && <div className="rnp-sp-l">{lspLabel[lsp.findIndex(([k]) => k === i)]}</div>}</td>}
          {i % 2 === 0 && <td rowSpan={2} className="rnp-grp" style={{ color: GROUP_COLOR[grp] }}>{grp}</td>}
          <td className="rnp-sub-l">{sub}</td>
          <td>{f(pd, fmt)}</td><td>{f(pm, fmt)}</td><td>{f(fc, fmt)}</td>
          <td className={pctCls}>{pct == null ? "" : Math.round(pct * 100) + "%"}</td>
          <td className="rnp-fact">{f(fact, fmt)}</td>
          {i % 2 === 0 && <td rowSpan={2} className="rnp-sp">
            {spk && <Spark vals={b.spark[spk] || []} color={col} kind={spk === "drr" ? "line" : "bar"} />}</td>}
          <td>{f(w[0], fmt)}</td><td>{f(w[1], fmt)}</td><td>{f(w[2], fmt)}</td>
          {!hideChg && <td className={dynCls}>{dyn == null ? "" : f(dyn, fmt)}</td>}
          {showDays && days.map((d) => {
            const v = b.days[d]?.[key];
            let cls = "";
            if (pd != null && v != null && (fmt !== "pct" || v !== 0)) cls = (lessBetter ? v <= pd : v >= pd) ? "d-good" : "d-bad";
            return <td key={d} className={cls}>{f(v, fmt)}</td>;
          })}
        </tr>
      );
    });
  };

  return (
    <div className="rnp">
      <div className="rnp-bar">
        <label>Месяц <select value={month} onChange={(e) => setMonth(e.target.value)}>
          {months.map((m) => <option key={m} value={m}>{MON[Number(m.slice(5, 7)) - 1]} {m.slice(0, 4)}</option>)}</select></label>
        <label>Сортировать по <select value={sort} onChange={(e) => setSort(e.target.value)}>
          {Object.entries(data?.sorts || { orders_sum: "Заказы, руб" }).map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select></label>
        <label>Бренд <select value={brand} onChange={(e) => setBrand(e.target.value)}><option value="">Все</option>
          {(data?.brands || []).map((x) => <option key={x}>{x}</option>)}</select></label>
        <label>Предмет <select value={subject} onChange={(e) => setSubject(e.target.value)}><option value="">Все</option>
          {(data?.subjects || []).map((x) => <option key={x}>{x}</option>)}</select></label>
        <label>Группа / тег <select value={group} onChange={(e) => setGroup(e.target.value)}><option value="">Все</option>
          {groups.map((g) => <option key={g.key} value={g.key}>{g.title}</option>)}</select></label>
        <label className="chk" title="«Хватит на»: учесть, что часть товара в пути к клиенту вернётся, и товар в пути от клиента">
          <input type="checkbox" checked={withBuyout} onChange={(e) => setWithBuyout(e.target.checked)} /> Учесть % выкупа</label>
        <button className={showLeft ? "on" : ""} onClick={() => setShowLeft(!showLeft)}>{showLeft ? "−" : "+"} графики слева</button>
        <button className={showDays ? "on" : ""} onClick={() => setShowDays(!showDays)}>{showDays ? "−" : "+"} дни месяца</button>
        {busy && <span className="hint">считаю…</span>}
      </div>
      {err && <div className="hint err">{err}</div>}
      {data?.stale && <div className="hint">Пришли новые данные — показан расчёт на {new Date(data.cached_at!).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}, свежий считается.</div>}
      {data && !data.error && <>
        {!data.has_plan && <div className="hint">Плана на этот месяц нет — столбцы плана пустые и без цветов. План задаётся во вкладке «Планирование».</div>}
        <div className="rnp-wrap">
          <table className="rnp-t">
            <thead>{head}</thead>
            <tbody>{block(data.total, true)}</tbody>
            {blocks.map((b) => <tbody key={b.nm_id}>{block(b, false)}</tbody>)}
          </table>
        </div>
        {blocks.length < data.count && <button className="rnp-more" disabled={busy} onClick={loadMore}>
          Показать ещё ({data.count - blocks.length} арт.)</button>}
      </>}
    </div>
  );
}
