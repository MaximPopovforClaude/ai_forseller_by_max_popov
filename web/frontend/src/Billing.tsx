import { useEffect, useState } from "react";
import { http } from "./api";

type Plan = { key: string; title: string; about: string; price_month: number | null; available?: boolean; unavailable_reason?: string | null };
type Pay = { id: number; plan: string; months: number; days: number; base_amount: number; discount: number; bonus_used: number; amount: number;
  promo_code: string | null; status: string; provider: string; pay_url: string | null; created_at: string; paid_at: string | null };
type Info = { workspace: { id: number; name: string; plan: string; plan_title?: string; plan_until: string | null }; plans: Plan[]; payments: Pay[]; can_pay: boolean;
  months: number[]; bonus: number; online: boolean };
type Quote = { error?: string; plan?: string; title?: string; months?: number; days?: number; base?: number; discount?: number; bonus?: number; amount?: number; promo?: string | null };

const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });
const d = (s: string | null) => (s ? new Date(s).toLocaleDateString("ru-RU") : "—");
const ST: Record<string, string> = { pending: "ждёт оплаты", paid: "оплачен", canceled: "отменён" };

export function Billing({ wsId }: { wsId: number }) {
  const [info, setInfo] = useState<Info | null>(null);
  const [plan, setPlan] = useState("");
  const [months, setMonths] = useState(1);
  const [promo, setPromo] = useState("");
  const [bonus, setBonus] = useState(false);
  const [q, setQ] = useState<Quote | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const load = () => http.get<Info>(`/api/billing/${wsId}`).then((x) => { setInfo(x); setPlan((p) => p || x.workspace.plan); }).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [wsId]);
  useEffect(() => {
    if (!info?.can_pay || !info.plans.some((p) => p.key === plan && p.available !== false)) { setQ(null); return; }
    const t = setTimeout(() => http.post<Quote>(`/api/billing/${wsId}/quote`, { plan, months, promo: promo || null, use_bonus: bonus }).then(setQ).catch((e) => setErr(e.message)), 300);
    return () => clearTimeout(t);
  }, [plan, months, promo, bonus, info]);
  if (err && !info) return <div className="err">{err}</div>;
  if (!info) return <div className="hint">Загрузка…</div>;
  const ws = info.workspace;
  const pay = () => http.post<{ status: string; pay_url?: string; message?: string }>(`/api/billing/${wsId}/checkout`, { plan, months, promo: promo || null, use_bonus: bonus })
    .then((r) => { if (r.pay_url) window.location.href = r.pay_url; else { setMsg(r.status === "paid" ? "Готово, тариф подключён." : r.message || "Заявка принята."); load(); } })
    .catch((e) => setErr(e.message));
  return (
    <div className="acc">
      <h2>Тариф и оплата · {ws.name}</h2>
      <div className="acc-box">
        <div className="acc-row"><span>Сейчас</span><b>{ws.plan_title || info.plans.find((p) => p.key === ws.plan)?.title || ws.plan}</b></div>
        <div className="acc-row"><span>Оплачено по</span>{ws.plan_until ? d(ws.plan_until) : "без срока"}</div>
        {info.bonus > 0 && <div className="acc-row"><span>Ваши бонусы</span>{nf.format(info.bonus)} ₽ (за приглашённых друзей)</div>}
      </div>
      <div className="plans">
        {info.plans.map((p) => (
          <div key={p.key} className={"plan" + (plan === p.key && p.available !== false ? " cur" : "")} aria-disabled={p.available === false}
            onClick={() => { if (p.available !== false) setPlan(p.key); }}>
            <div className="plan-t">{p.title}{ws.plan === p.key && <span className="plan-badge">текущий</span>}{p.available === false && <span className="plan-badge">скоро</span>}</div>
            <div className="plan-a">{p.unavailable_reason || p.about}</div>
            <div className="plan-p">{p.available === false ? "Подключение пока недоступно" : p.price_month == null ? "цена уточняется" : `${nf.format(p.price_month)} ₽ / мес.`}</div>
          </div>
        ))}
      </div>
      {info.can_pay ? (
        <div className="acc-box">
          <b>Оплатить</b>
          <div className="acc-row"><span>Срок</span>
            <select value={months} onChange={(e) => setMonths(Number(e.target.value))}>{info.months.map((m) => <option key={m} value={m}>{m} мес.</option>)}</select></div>
          <div className="acc-row"><span>Промокод</span><input value={promo} onChange={(e) => setPromo(e.target.value.toUpperCase())} placeholder="если есть" /></div>
          {info.bonus > 0 && <label className="acc-row"><span>Бонусы</span><input type="checkbox" checked={bonus} onChange={(e) => setBonus(e.target.checked)} /> списать бонусы</label>}
          {q?.error ? <div className="err">{q.error}</div> : q && (
            <div className="quote">
              {q.days ? <>Промокод даёт <b>{q.days} дн.</b> тарифа «{q.title}» бесплатно.</> : <>
                {nf.format(q.base!)} ₽{q.discount ? <> − скидка {nf.format(q.discount)} ₽</> : null}{q.bonus ? <> − бонусы {nf.format(q.bonus)} ₽</> : null}
                {" "}= <b>{nf.format(q.amount!)} ₽</b></>}
            </div>
          )}
          <button disabled={!q || !!q.error || !info.plans.some((p) => p.key === plan && p.available !== false)} onClick={pay}>{q?.amount ? (info.online ? "Перейти к оплате" : "Отправить заявку на оплату") : "Подключить"}</button>
          {!info.online && <div className="hint">Онлайн-оплата картой подключается; пока заявка уходит нам, счёт пришлём и тариф включим вручную.</div>}
          {msg && <div className="ok">{msg}</div>}
          {err && <div className="err">{err}</div>}
        </div>
      ) : <div className="hint">Оплачивает владелец или админ кабинета.</div>}
      {info.payments.length > 0 && (
        <div className="acc-box">
          <b>Платежи</b>
          <table className="board-t"><thead><tr><th>№</th><th>Дата</th><th>Тариф</th><th>Срок</th><th>Сумма</th><th>Промокод</th><th>Статус</th></tr></thead>
            <tbody>{info.payments.map((p) => (
              <tr key={p.id}><td>{p.id}</td><td>{d(p.created_at)}</td><td>{info.plans.find((x) => x.key === p.plan)?.title || p.plan}</td>
                <td>{p.months ? `${p.months} мес.` : ""}{p.days ? ` ${p.days} дн.` : ""}</td><td className="n">{nf.format(p.amount)} ₽</td><td>{p.promo_code || ""}</td>
                <td>{ST[p.status] || p.status}{p.status === "pending" && p.pay_url && <> · <a href={p.pay_url}>оплатить</a></>}</td></tr>))}</tbody></table>
        </div>
      )}
    </div>
  );
}

type Ref = { code: string; site_link: string; bot_link: string | null; percent: number; invited: number; paid: number; earned: number; balance: number;
  rows: { email: string; created_at: string; reward: number }[] };

export function Referral() {
  const [r, setR] = useState<Ref | null>(null);
  const [err, setErr] = useState("");
  const [copied, setCopied] = useState("");
  useEffect(() => { http.get<Ref>("/api/me/referral").then(setR).catch((e) => setErr(e.message)); }, []);
  if (err) return <div className="err">{err}</div>;
  if (!r) return <div className="hint">Загрузка…</div>;
  const copy = (t: string) => navigator.clipboard?.writeText(t).then(() => { setCopied(t); setTimeout(() => setCopied(""), 2000); });
  return (
    <div className="acc">
      <h2>Пригласить друга</h2>
      <div className="acc-box">
        Делитесь ссылкой: с каждой оплаты приглашённого вы получаете <b>{nf.format(r.percent)} %</b> бонусами на свой счёт.
        Бонусами можно оплатить тариф (1 бонус = 1 ₽).
        {r.bot_link && <div className="acc-row"><span>Регистрация в Telegram</span><code>{r.bot_link}</code>
          <button onClick={() => copy(r.bot_link!)}>{copied === r.bot_link ? "Скопировано" : "Копировать"}</button></div>}
        <div className="acc-row"><span>Ссылка на сайт</span><code>{r.site_link}</code>
          <button onClick={() => copy(r.site_link)}>{copied === r.site_link ? "Скопировано" : "Копировать"}</button></div>
        <div className="acc-row"><span>Ваш код</span><b>{r.code}</b></div>
      </div>
      <div className="ins-cards">
        <div className="ins-card"><div className="hint">Пришло по ссылке</div><b>{r.invited}</b></div>
        <div className="ins-card"><div className="hint">Из них оплатили</div><b>{r.paid}</b></div>
        <div className="ins-card"><div className="hint">Начислено всего</div><b>{nf.format(r.earned)} ₽</b></div>
        <div className="ins-card"><div className="hint">Баланс бонусов</div><b>{nf.format(r.balance)} ₽</b></div>
      </div>
      {r.rows.length > 0 && <div className="acc-box"><b>Приглашённые</b>
        <table className="board-t"><tbody>{r.rows.map((x, i) => <tr key={i}><td>{x.email}</td><td>{d(x.created_at)}</td><td className="n">{nf.format(x.reward)} ₽</td></tr>)}</tbody></table></div>}
    </div>
  );
}
