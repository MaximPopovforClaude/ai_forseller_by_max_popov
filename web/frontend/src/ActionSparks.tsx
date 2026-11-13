import { useEffect, useRef, useState } from "react";

export type ActionChartData = { days: string[]; rows: Record<string, Record<string, (number | null)[]>>; price_label: string; note: string; error?: string };
const fmt = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });
const metrics = [["orders", "Заказы, шт.", "#2f3fd8"], ["buyouts", "Выкупы, шт.", "#d97706"],
  ["price_spp", "Цена с СПП, ₽", "#7c3aed"], ["ads", "Рекламный бюджет, ₽", "#dc2626"], ["profit", "Прибыль расчётная, ₽", "#16a34a"]];

/** SVG charts are mounted only near the viewport, so a large shop stays usable. */
export function ActionSparks({ data, nm }: { data: ActionChartData | undefined; nm: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(typeof IntersectionObserver === "undefined");
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined" || !ref.current) return;
    const observer = new IntersectionObserver(entries => setVisible(entries[0].isIntersecting), { rootMargin: "300px" });
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  const row = data?.rows?.[String(nm)];
  return <div ref={ref} className="action-sparks">
    {!data ? <span className="hint">Загрузка графиков…</span> : data.error ? <span className="hint">{data.error}</span> : !row ? <span className="hint">Нет истории для графиков</span> : visible && metrics.map(([key, title, color]) => {
      const vals = row[key] || [], known = vals.filter((v): v is number => v != null && Number.isFinite(v));
      const label = key === "price_spp" ? data.price_label : title;
      const lo = key === "price_spp" ? Math.min(...known) : Math.min(0, ...known), hi = key === "price_spp" ? Math.max(...known) : Math.max(0, ...known), range = hi - lo || 1, w = 150, h = 26;
      const y = (v: number) => h - 2 - (v - lo) / range * (h - 4), step = w / Math.max(vals.length, 1);
      const tip = (i: number, v: number) => `${data.days[i]?.split('-').reverse().join('.')}: ${fmt.format(v)}`;
      return <div className="action-spark" key={key}>
        <span>{label}</span>
        {!known.length ? <small className="hint">нет данных</small> : <svg width={w} height={h} role="img" aria-label={`${label}, ${data.days[0]} — ${data.days[data.days.length-1]}`}>
          <title>{label}. Наведи на значение, чтобы увидеть день и число.</title>
          {vals.map((v, i) => v == null || !Number.isFinite(v) ? null : key === "price_spp" ? <g key={i}>
            {i > 0 && vals[i-1] != null && <line x1={(i-.5)*step} y1={y(vals[i-1]!)} x2={(i+.5)*step} y2={y(v)} stroke={color} />}
            <circle cx={(i+.5)*step} cy={y(v)} r={2.5} fill={color}><title>{tip(i,v)}</title></circle>
          </g> : <rect key={i} x={i*step+.5} width={Math.max(1,step-1)} y={Math.min(y(v),y(0))} height={Math.max(1,Math.abs(y(v)-y(0)))} fill={v < 0 ? '#dc2626' : color}>
            <title>{tip(i,v)}</title></rect>)}
        </svg>}
      </div>;
    })}
  </div>;
}
