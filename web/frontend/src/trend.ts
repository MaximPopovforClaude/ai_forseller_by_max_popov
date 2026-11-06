import type { Col } from "./api";

/** Раскраска листов-дашбордов : каждое значение сравниваем с соседним предыдущим периодом справа
 * (день с прошлым днём, неделя с прошлой неделей…). Направление «хорошо/плохо» — по смыслу строки: рост расходов, отмен,
 * возвратов, ДРР — красный; рост заказов, выкупов, маржи, прибыли — зелёный; цены и СПП — без цвета. */
export type TrendMode = "none" | "fill" | "text";
export const PNL_TABS = /^(pnl_(?!.*no_cost)|opiu|fin_sku|ym_fin_sku)/;   // вкладки PnL: прибыль красим по знаку 
export const COL_TREND_TABS = ["svodwb", "svod", "abc"];
const BAD_UP = /отмен|невыкуп|возврат|комисси|логистик|себестоимост|реклам|хранени|приемк|приёмк|налог|ндс к начисл|расход|затрат|эквайринг|cpc|cpm/i;
export const KEY_ROW = /^(кол-во заказов всего|заказы: количество|сумма заказов с учетом скидки продавца|кол-во выкупов|выкупы: количество|сумма выкупов до скидки|маржа, руб|маржа по заказам с учётом процента выкупа, руб|прибыль|оперативная прибыль|расходы на рекламу|дрр от суммы заказов|к оплате продавцу)/i;
export function rowDir(label: string): number {
  const l = label.toLowerCase();
  if (/^(прибыль|оперативная прибыль)/.test(l) || l.includes("неотменен")) return 1;   // «за минусом налога» — это прибыль
  if (l.includes("дрр")) return -1;
  if (l.startsWith("реклама (") && !/затрат|расход|сумма расход/.test(l)) return 1;   // результаты рекламы: показы, клики, заказы
  if (l.startsWith("средняя")) return 0;                                                 // средняя цена, средняя СПП
  return BAD_UP.test(l) ? -1 : 1;
}
/** Пары «столбец → предыдущий период»: соседний справа, того же вида (дни с днями, месяцы с месяцами), не через «изм.». */
export function trendPairs(cols: Col[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (let i = 0; i < cols.length - 1; i++) {
    const a = cols[i], b = cols[i + 1];
    if (a.type !== "rowfmt" || b.type !== "rowfmt") continue;
    if (/^\d{4}-/.test(a.field) && a.field.length !== b.field.length) continue;
    if (/\(по /.test(a.title)) continue;            // неполный текущий месяц не сравниваем 
    out[a.field] = b.field;
  }
  // 5#Дашборд: прогноз текущего месяца сравниваем с прошлым месяцем (столбец сразу за неполным текущим)
  const part = cols.findIndex((c) => c.type === "rowfmt" && /\(по /.test(c.title));
  const fc = cols.find((c) => c.type === "rowfmt" && /^прогноз/i.test(c.title));
  if (part >= 0 && fc && cols[part + 1]?.type === "rowfmt") out[fc.field] = cols[part + 1].field;
  return out;
}

/** Сводные по артикулам : красим столбцы. Пара «показатель за период → тот же показатель за предыдущий период»
 * (вчера→позавчера, неделя→прошлая неделя, месяц→прошлый месяц); «разница» — по знаку; смысл показателя — как в rowDir. */
export const KEY_COL = /заказ|выкуп|выручк|к оплате|маржа|маржинальн|прибыль|реклам|дрр/i;
export const SKIP_COL = /отмен|невыкуп|возврат|остат|себестоимост|стоимост|рейтинг|в пути|средн|^артикул|идентификатор/i;
const PERIODS: [RegExp, string, number][] = [
  [/сегодня/i, "d", 0], [/позавчера/i, "d", 2], [/вчера/i, "d", 1],
  [/текущ\S* недел/i, "w", 0], [/позапрошл\S* недел/i, "w", 2], [/(предыдущ|прошл)\S* недел/i, "w", 1],
  [/текущ\S* месяц/i, "m", 0], [/позапрошл\S* месяц/i, "m", 2], [/(предыдущ|прошл)\S* месяц/i, "m", 1],
];
function colTime(c: Col): { key: string; unit: string; rank: number } | null {
  const ym = c.field.match(/^(.*)_(\d{6})$/);
  if (ym) return { key: ym[1], unit: "m", rank: -Number(ym[2]) };
  const per = c.period || (c.title.includes(" · ") ? c.title.split(" · ")[1] : c.title.match(/ за (.+)$/i)?.[1]) || "";
  for (const [re, unit, rank] of PERIODS) if (re.test(per)) {
    const key = (c.metric || c.title.split(" · ")[0].replace(/ за .+$/i, "")).trim().toLowerCase();
    return { key, unit, rank };
  }
  return null;
}
export function colPairs(cols: Col[]): Record<string, string> {
  const t = cols.map(colTime);
  const out: Record<string, string> = {};
  cols.forEach((c, i) => {
    const a = t[i];
    if (!a) return;
    let best = -1;
    cols.forEach((_, j) => { const b = t[j]; if (b && j !== i && b.key === a.key && b.unit === a.unit && b.rank > a.rank && (best < 0 || b.rank < t[best]!.rank)) best = j; });
    if (best >= 0) out[c.field] = cols[best].field;
  });
  return out;
}

