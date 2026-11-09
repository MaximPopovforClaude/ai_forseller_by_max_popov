import type { TabData } from "./api";
import { rowDir } from "./trend";

const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });

function fmt(v: unknown, f: string) {
  if (v == null) return "Нет данных";
  const n = Number(v);
  return f === "pct" ? nf1.format(n * 100) + " %" : nf.format(n) + (f === "money" ? " ₽" : "");
}

/** Главная магазина: карточки ключевых показателей — сегодня (неполный день), вчера, позавчера. */
export function Home({ data, hideChg = false }: { data: TabData; hideChg?: boolean }) {
  const [, c1, c2, c3] = data.columns;
  return (
    <div className="home">
      {data.rows.map((r) => {
        const y = Number(r.D ?? 0), y2 = Number(r.F ?? 0);
        const ch = r.fmt === "pct" ? (y - y2) * 100 : y2 ? (y / y2 - 1) * 100 : 0;
        return (
          <div key={String(r.label)} className="card">
            <div className="card-t">{String(r.label)}</div>
            <div className="card-v">{fmt(r.D, String(r.fmt))}<span className="card-s">{c2.title}</span></div>
            <div className="card-row">
              <span>{c1.title}: <b>{fmt(r.C, String(r.fmt))}</b></span>
              <span>{c3.title}: <b>{fmt(r.F, String(r.fmt))}</b></span>
            </div>
            {!hideChg && r.D != null && r.F != null && y2 !== 0 && <div className={ch * (rowDir(String(r.label)) || 1) >= 0 ? "up" : "down"}>{ch >= 0 ? "▲" : "▼"} {nf1.format(Math.abs(ch))}{r.fmt === "pct" ? " п.п." : " %"} к позавчера</div>}
          </div>
        );
      })}
      <div className="hint">{data.hint ? String(data.hint) : data.ozon ? "Расчёт — как в Version2 «По дням». Продажи и прибыль Ozon дописывает по начислениям с задержкой в 1–2 дня."
        : `${data.columns[0].title}. Формулы — как в 5#Дашборд (прибыль по заказам — с % выкупа за 4 недели).`}</div>
    </div>
  );
}
