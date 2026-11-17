export type Kind = { key: string; title: string; color: string; unit?: string };
export type Act = { id: number | string; kind: string; value: string | null; note?: string | null; who?: string; user_id?: number; auto?: boolean; color?: string | null;
  created_at?: string | null; detected_at?: string | null; wb_updated_at?: string | null };
export type AdMetric = { campaigns: number; spent: number | null; campaign_spent: number | null; budget: number | null; daily_limit: number | null;
  usage_limit: number | null; usage_balance: number | null; bids: Record<string, number | null>; partial: string[]; observed_at: string[];
  budget_at?: string[]; limit_at?: string[]; classification_estimated?: boolean;
  payment_spend?: Record<string, { spent: number | null; campaigns: number; partial: boolean; classification_estimated?: boolean }> };

export const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
export const nf1 = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
export const pct = (v: number | null) => (v == null ? "" : nf1.format(v * 100) + " %");
export const num = (v: number | null) => (v == null ? "" : nf.format(v));
// ДРР в ячейках дня : общий, по виду рекламы (АРК / ПРК) и по направлению (поиск / рекомендации)
export const DRR: [string, string, string][] = [["all", "общий", "ДРР"], ["ark", "АРК", "АРК"], ["prk", "ПРК", "ПРК"], ["search", "поиск", "Поиск"], ["rec", "рекомендации", "Реком."]];
const DEEP_ADS = new Set(["auto:ad_kw_bid", "auto:ad_kw_minus", "auto:ad_kw_status", "auto:ad_setting",
  "auto:ad_product", "auto:ad_budget", "auto:ad_limit", "auto:ad_command", "auto:ad_config"]);
export const visibleAct = (a: Act, deep: boolean) => deep || !DEEP_ADS.has(a.kind);
export const PRICE_NOTE = "Средняя цена с СПП в заказах статистики WB за день, как на графике РНП. Без заказов или данных — прочерк. Сегодня — неполный день.";
export const AD_GROUPS = [["all", "Вся реклама"], ["cpm", "CPM"], ["cpc", "CPC"], ["search", "Поиск"], ["rest", "Вне поиска · оценка"], ["prk", "ПРК"], ["unknown", "Тип оплаты неизвестен"]];
export const AD_CLASS_NOTE = "CPM/CPC — способ оплаты. «Вне поиска» — оценка по разнице расходов, а не подтверждённое место показа. Разбивки по оплате и месту не складываются между собой.";
export const AD_ORDER_NOTE = "Через слэш: остаток бюджета / потрачено на товар / дневной лимит / использование бюджета / ставка CPM / ставка CPC. Деньги — в рублях; CPM — за 1000 показов, CPC — за клик. Порядок одинаков во всех группах. Ноль и отсутствие данных показаны прочерком; наведи на значение, чтобы различить их. * — неполные данные, ≈ — тип РК взят из последних настроек и не подтверждён на этот день. Ниже поиска и вне поиска — отдельно расходы CPM / CPC (и неизвестного типа, если он есть).";
export const AD_NOTE = "Расход товара — за день. Бюджет — общий остаток связанных РК на последнем замере дня; он не делится между товарами и не складывается по артикулам. Процент — оценка по расходу всей кампании: к базовому дневному лимиту (без переноса остатка) либо к расходу плюс остатку. Вне поиска — оценка: расход товара в РК минус расход поисковых кластеров той же РК/товара/дня. Пропуск, неполный ответ или отрицательная разница не дают остатка. Для смешанных мест показа отдельных бюджетов поиска и вне поиска нет. Средняя ставка — простое среднее настроенных ставок товара по включённым местам, без ставок отдельных ключей; CPM и CPC не смешиваются. Группы пересекаются: ПРК — ручные ставки, поиск — расходы поиска. Без дневного снимка только тип оплаты/режим ставок берём из последних сохранённых настроек, как в точках входа, и подписываем это; исторический тип тогда не подтверждён. Текущие суммы, ставки и места показа назад не переносим. История бюджета/ставок начинается с новых снимков; прочерк — нет наблюдения, звёздочка — неполная сумма или среднее по известной части. Сегодняшний день не завершён.";

const stampDate = new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Moscow", year: "numeric", month: "2-digit", day: "2-digit" });
const stampTime = new Intl.DateTimeFormat("ru-RU", { timeZone: "Europe/Moscow", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
function stamp(raw?: string | null, day?: string) {
  if (!raw || !/(Z|[+-]\d\d:\d\d)$/i.test(raw)) return null;
  const t = new Date(raw); if (!Number.isFinite(t.getTime())) return null;
  const parts = stampDate.format(t);
  const time = stampTime.format(t);
  return `${parts === day ? "" : parts.slice(8,10) + "." + parts.slice(5,7) + "." + parts.slice(0,4) + " "}${time} МСК`;
}
function actionTime(a: Act, day?: string) {
  if (!a.auto) return `Записано: ${stamp(a.created_at, day) || "время неизвестно"}`;
  if (a.kind === "auto:promo_day" || a.kind === "auto:entry") return "";
  const label = a.kind === "auto:ad_command" ? "Принято WB" : a.kind === "auto:ad_config" ? "Записано" : "Замечено";
  const updated = stamp(a.wb_updated_at, day);
  return `${label}: ${stamp(a.detected_at, day) || "время неизвестно"}${updated ? ` · Карточка обновлена МП: ${updated}` : ""}`;
}
type AdValue = { label: string; number: number | null | undefined; unit?: string; partial?: boolean };
const smallAdNumber = new Intl.NumberFormat("ru-RU", { maximumSignificantDigits: 3 });
function adNumber(n: number | null | undefined) {
  if (n == null || !Number.isFinite(n) || n === 0) return "—";
  return (Math.abs(n) < .1 ? smallAdNumber : nf1).format(n);
}
function AdValues({ values }: { values: AdValue[] }) {
  return <div className="action-ad-values">{values.map((v, i) => {
    const known = v.number != null && Number.isFinite(v.number);
    const hint = `${v.label}: ${known ? (v.number === 0 ? "0" : adNumber(v.number)) + (v.unit || "") : "нет данных"}${v.partial ? ". Неполные данные" : ""}`;
    return <span className="action-ad-part" key={v.label}>
      {i > 0 && <span className="action-ad-separator" aria-hidden="true"> / </span>}
      <strong title={hint} aria-label={hint}>{adNumber(v.number)}{known && v.number !== 0 && v.unit === " %" ? "%" : ""}{v.partial ? "*" : ""}</strong>
    </span>;
  })}</div>;
}
function AdStats({ data, groups, basis }: { data?: Record<string, AdMetric>; groups: string[]; basis: "limit" | "balance" }) {
  return <div className="action-ad-stats">{AD_GROUPS.filter(([k]) => groups.includes(k) && (k !== "unknown" || (data?.unknown?.campaigns ?? 0) > 0)).map(([key, title]) => {
    const m = data?.[key];
    const value = (n: number | null | undefined, field: string, suffix = " ₽") => n == null ? "нет данных" : nf1.format(n) + suffix + (m?.partial?.includes(field) ? " *" : "");
    const usage = m?.[basis === "limit" ? "usage_limit" : "usage_balance"];
    const metric = (field: string, label: string, n: number | null | undefined, unit = " ₽"): AdValue =>
      ({ label, number: n, unit, partial: m?.partial?.includes(field) });
    const values = [metric("budget", "Остаток бюджета РК", m?.budget), metric("spent", "Потрачено · товар", m?.spent),
      metric("daily_limit", "Дневной лимит РК", m?.daily_limit),
      metric(basis === "limit" ? "usage_limit" : "usage_balance", basis === "limit" ? "Расход / дневной лимит" : "Расход / (расход + остаток)", usage == null ? null : usage * 100, " %"),
      metric("bid_cpm", "Средняя ставка CPM", m?.bids?.cpm, " ₽/1000 показов"), metric("bid_cpc", "Средняя ставка CPC", m?.bids?.cpc, " ₽/клик")];
    return <div key={key} className="action-ad-group" title={`Кампаний с данными: ${m?.campaigns ?? 0}. Расход этих РК (все товары): ${value(m?.campaign_spent, "campaign_spent")}. Последние снимки настроек: ${m?.observed_at?.map(t => stamp(t)).join(", ") || "нет"}. Бюджета: ${m?.budget_at?.map(t => stamp(t)).join(", ") || "нет"}. Лимита: ${m?.limit_at?.map(t => stamp(t)).join(", ") || "нет"}. * Неполная сумма или среднее по известной части. Подробности — над таблицей.`}>
      <b>{title}</b>
      {m?.classification_estimated && <span className="action-ad-estimated" title="Группировка по последним настройкам РК; на этот день тип не подтверждён." aria-label="Тип РК на этот день не подтверждён"> ≈</span>}
      <AdValues values={values} />
      {key === "all" && (data?.unknown?.campaigns ?? 0) > 0 && <div className="action-ad-extra">
        <span className="hint" title="Расход с неизвестным типом оплаты; уже входит в общий расход">Тип неизвестен</span>
        <AdValues values={[{label: "Не распределено по CPM/CPC", number: data?.unknown?.spent, unit: " ₽", partial: data?.unknown?.partial?.includes("spent")}]} />
      </div>}
      {(key === "search" || key === "rest") && <div className="action-ad-extra">
        <span className="hint">CPM / CPC{(m?.payment_spend?.unknown?.campaigns ?? 0) > 0 ? " / ?" : ""}</span>
        <AdValues values={["cpm", "cpc", "unknown"].filter(model => model !== "unknown" || (m?.payment_spend?.unknown?.campaigns ?? 0) > 0).map(model => {
        const part = m?.payment_spend?.[model];
        return {label: `Расход ${model === "unknown" ? "неизвестного типа" : model.toUpperCase()}`, number: part?.spent, unit: " ₽", partial: part?.partial};
      })} /></div>}
    </div>;
  })}</div>;
}

const AUTO: Record<string, { title: string; color: string }> = {
  // цвета : цена ↑ зелёный / ↓ красный (приходит с сервера), акции розовый, фото и карточка синий, реклама жёлтый,
  // характеристики бирюзовый (с сервера), прочее — свои цвета
  "auto:price": { title: "Цена", color: "#16a34a" }, "auto:content": { title: "Карточка", color: "#2563eb" },
  "auto:photo": { title: "Фото", color: "#2563eb" }, "auto:size": { title: "Размеры", color: "#f97316" },
  "auto:ad_status": { title: "Реклама", color: "#ca8a04" }, "auto:ad_bid": { title: "Ставка", color: "#ca8a04" },
  "auto:ad_kw_bid": { title: "Ставка ключа", color: "#ca8a04" }, "auto:ad_kw_minus": { title: "Минус-фразы", color: "#ca8a04" },
  "auto:ad_kw_status": { title: "Ключ рекламы", color: "#ca8a04" },
  "auto:ad_setting": { title: "Настройки РК", color: "#ca8a04" }, "auto:ad_product": { title: "Товары РК", color: "#ca8a04" },
  "auto:ad_budget": { title: "Остаток бюджета", color: "#ca8a04" }, "auto:ad_limit": { title: "Дневной лимит", color: "#ca8a04" },
  "auto:ad_command": { title: "Команда через платформу", color: "#ca8a04" }, "auto:ad_config": { title: "Настройки блока", color: "#ca8a04" },
  "auto:promo": { title: "Акция", color: "#db2777" }, "auto:promo_day": { title: "В акции", color: "#f472b6" },
  "auto:entry": { title: "Точка входа", color: "#dc2626" },   // цвет с сервера: рост зелёный, просадка красный
};

export function chip(a: Act, kinds: Record<string, Kind>, day?: string) {
  const k = kinds[a.kind];
  const au = AUTO[a.kind];
  const title = k?.title || au?.title || a.kind.replace(/^custom:/, "");
  const color = a.color || k?.color || au?.color || "#6b7280";
  const label = a.auto ? a.value || title : title + (a.value ? " " + a.value + (k?.unit && !/[₽шт%]/.test(a.value) ? " " + k.unit : "") : "");
  const time = actionTime(a, day), timeTitle = day ? actionTime(a) : time;
  return (
    <span key={a.id} className={"chip" + (a.auto ? " auto" : "")} style={{ borderColor: color, color }}
      title={(a.auto ? (a.kind === "auto:ad_command" ? "WB принял команду через платформу: " : a.kind === "auto:ad_config" ? "Настройка платформы: " : "Заметили сами (API): ") : (a.who ? a.who + ": " : "")) + label + (a.note ? "\n" + a.note : "") + (timeTitle ? "\n" + timeTitle : "")}>
      {a.auto ? "⚙ " : ""}{label}
      {time && <small className="action-time">{time}</small>}
    </span>
  );
}


export type DayRow = {
  orders_source?: string; mp?: string;
  orders: Record<string, number>; actions: Record<string, Act[]>;
  price_spp_days?: Record<string, number | null>;
  ad_metrics?: Record<string, Record<string, AdMetric>>;
  ads?: Record<string, { all: number; ark: number; prk: number; search: number; rec: number; osum: number | null }>;
};
export function ActionDayContent({row: r, day: d, kinds, drr, deepAds, dayPrices, adStats, adGroups, adBasis}: {
  row: DayRow; day: string; kinds: Record<string, Kind>; drr: string[]; deepAds: boolean;
  dayPrices: boolean; adStats: boolean; adGroups: string[]; adBasis: "limit" | "balance";
}) {
  const o = r.orders[d] ?? (r.orders_source === "wb_funnel" ? null : 0);
  const prevDay = new Date(new Date(d).getTime() - 864e5).toISOString().slice(0, 10);
  const p = r.orders[prevDay];
  const acts = (r.actions[d] || []).filter(a => visibleAct(a, deepAds));
  const price = r.price_spp_days?.[d];
  return <>
    <div title={r.orders_source === "wb_funnel" ? "Заказы по воронке WB; прочерк — нет данных полного дня" : undefined}
      className={"o" + (o != null && p != null && o > p ? " up" : o != null && p != null && o < p ? " down" : "")}>{o ?? "—"}</div>
    {drr.length > 0 && r.ads?.[d] && <div className="hint" style={{ fontSize: 11, lineHeight: 1.25, whiteSpace: "nowrap" }}>
      {DRR.filter(([k]) => drr.includes(k)).map(([k, , short]) => { const a = r.ads![d], v = a[k as "all"];
        return v ? <div key={k}>{short} {a.osum ? nf1.format(v / a.osum * 100) + "%" : nf.format(v) + " ₽"}</div> : null; })}</div>}
    {dayPrices && r.mp === "wb" && <div className="hint action-day-price" title={PRICE_NOTE}>
      Цена с СПП: {price == null ? "—" : num(price) + " ₽"}</div>}
    {adStats && r.mp === "wb" && <AdStats data={r.ad_metrics?.[d]} groups={adGroups} basis={adBasis} />}
    {acts.map((a) => chip(a, kinds, d))}
  </>;
}
