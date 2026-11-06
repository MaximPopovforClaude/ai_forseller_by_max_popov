import { useEffect, useState } from "react";
import { http } from "./api";

type Block = { key: string; title: string; about: string; soon: boolean; available: boolean; scope: string | null; scope_ok: boolean;
  enabled: boolean; settings: Record<string, string | number | boolean> };
type WT = { scopes: string[]; exp: string | null; added_at: string; added_by: string; seller_oid: number };
type Log = { created_at: string; block: string; action: string; target: string | null; ok: boolean; error: string | null; by_ai: boolean; who: string | null };
type St = { marketplace: string; role: string; can_admin: boolean; paused: boolean; blocks: Block[]; modes: string[];
  write_token: WT | boolean | null; price_token: WT | boolean | null; split: boolean;
  ai: { ok: boolean; reason: string | null }; disclaimer: { version: string; text: string }; log: Log[] };

export const MODE_T: Record<string, string> = { off: "Выключено", manual: "Только вручную", draft: "ИИ пишет черновик, сотрудник отправляет", auto: "ИИ отвечает сам" };
const dt = (s: string) => new Date(s).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });

/** Взаимодействия с кабинетом: ключ на запись (с дисклеймером), блоки по отдельности, «Стоп», журнал действий. */
export function Actions({ shop }: { shop: number }) {
  const [s, setS] = useState<St | null>(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [tok, setTok] = useState("");
  const [cid, setCid] = useState("");
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const load = () => http.get<St>(`/api/shops/${shop}/actions`).then(setS).catch((e) => setErr(e.message));
  useEffect(() => { setS(null); setErr(""); load(); }, [shop]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!s) return <div className="acc">{err ? <div className="err">{err}</div> : <div className="hint">Загрузка…</div>}</div>;
  const ok = (t: string) => { setMsg(t); setErr(""); setTimeout(() => setMsg(""), 2500); };
  const saveBlock = (b: Block, enabled: boolean, settings: Block["settings"]) =>
    http.put(`/api/shops/${shop}/actions/${b.key}`, { enabled, settings }).then(() => { ok("Сохранено"); load(); }).catch((e) => setErr(e.message));
  const wt = typeof s.write_token === "object" ? s.write_token : null;
  return (
    <div className="acc actions">
      <h2>🤝 Взаимодействия с кабинетом</h2>
      <p className="hint">Здесь вы разрешаете сервису вносить изменения в кабинет маркетплейса. Каждый блок включается отдельно; всё, что сервис
        сделал, — в журнале внизу. Обычные таблицы и сводки работают на ключе «только чтение» и от этих настроек не зависят.</p>
      {err && <div className="err">{err}</div>}
      {msg && <div className="ok">{msg}</div>}

      <div className={"acc-box" + (s.paused ? " paused" : "")}>
        <b>{s.paused ? "⛔ Все взаимодействия остановлены" : "Статус"}</b>
        {s.paused ? <div className="hint">Сервис ничего не меняет в кабинете. Черновики можно смотреть, но не отправлять.</div>
          : <div className="hint">Если что-то пошло не так — нажмите «Стоп»: сервис сразу перестанет что-либо менять в кабинете.</div>}
        <div>{s.paused
          ? (s.can_admin ? <button className="pri" onClick={() => http.put(`/api/shops/${shop}/actions/paused`, { paused: false }).then(load).catch((e) => setErr(e.message))}>Возобновить</button>
            : <span className="hint">Возобновить может админ или владелец</span>)
          : <button className="danger" onClick={() => http.put(`/api/shops/${shop}/actions/paused`, { paused: true }).then(load).catch((e) => setErr(e.message))}>⛔ Стоп всё</button>}</div>
      </div>

      <div className="acc-box">
        <b>🔑 {s.split ? "Основной ключ на запись (без цен)" : "Ключ на запись"}</b>
        {wt ? <>
          <div>Добавлен {dt(wt.added_at)}{wt.added_by ? ` (${wt.added_by})` : ""}{wt.exp ? `, действует до ${new Date(wt.exp).toLocaleDateString("ru-RU")}` : ""}</div>
          <div className="hint">{s.marketplace === "ozon" ? "Роли" : "Разделы"}: {wt.scopes.join(", ") || "—"}</div>
          {s.can_admin && <div><button onClick={() => { if (window.confirm("Удалить ключ на запись? Сервис перестанет вносить изменения в кабинет.")) http.del(`/api/shops/${shop}/actions/write_token`).then(() => { ok("Ключ удалён"); load(); }).catch((e) => setErr(e.message)); }}>Удалить ключ</button></div>}
        </> : s.write_token === true ? <div>Ключ добавлен (подробности видит админ).</div>
          : !s.can_admin ? <div className="hint">Ключ на запись не добавлен. Добавляет админ или владелец кабинета.</div>
          : s.marketplace === "ozon" ? <>
            <div className="hint">Отдельный ключ Ozon (Настройки → Seller API) с ролью, у которой есть право изменений (например, Admin), — не «только чтение».
              Client-Id — тот же, что у магазина. Отвечать на отзывы через API Ozon можно только с подпиской Premium Pro.</div>
            <div className="disclaimer">⚠️ {s.disclaimer.text}</div>
            <label><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} /> Понимаю и согласен: буду проверять и контролировать действия сервиса</label>
            <div className="row">
              <input className="tok-in" placeholder="Client-Id" value={cid} onChange={(e) => setCid(e.target.value.replace(/\D/g, ""))} autoComplete="off" />
              <input type="password" className="tok-in" placeholder="Api-Key с правом изменений" value={tok} onChange={(e) => setTok(e.target.value)} autoComplete="off" />
              <button className="pri" disabled={!agree || tok.length < 20 || !cid || busy} onClick={() => { setBusy(true);
                http.put(`/api/shops/${shop}/actions/write_token`, { token: tok, client_id: cid, agree, version: s.disclaimer.version })
                  .then(() => { setTok(""); setCid(""); setAgree(false); ok("Ключ проверен и сохранён"); load(); }).catch((e) => setErr(e.message)).finally(() => setBusy(false)); }}>
                {busy ? "Проверяю…" : "Сохранить ключ"}</button>
            </div>
          </> : s.marketplace === "wb" ? <>
            <div className="hint">Отдельный ключ WB (Личный кабинет → Настройки → Доступ к API) <b>без</b> галочки «Только чтение», с разделами тех блоков, которые
              хотите включить (для отзывов — «Вопросы и отзывы»). Ключ должен быть от того же кабинета продавца, что и ключ магазина.</div>
            <div className="disclaimer">⚠️ {s.disclaimer.text}</div>
            <label><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} /> Понимаю и согласен: буду проверять и контролировать действия сервиса</label>
            <div className="row">
              <input type="password" className="tok-in" placeholder="Ключ API WB с правом записи" value={tok} onChange={(e) => setTok(e.target.value)} autoComplete="off" />
              <button className="pri" disabled={!agree || tok.length < 20 || busy} onClick={() => { setBusy(true);
                http.put(`/api/shops/${shop}/actions/write_token`, { token: tok, agree, version: s.disclaimer.version })
                  .then(() => { setTok(""); setAgree(false); ok("Ключ проверен и сохранён"); load(); }).catch((e) => setErr(e.message)).finally(() => setBusy(false)); }}>
                {busy ? "Проверяю…" : "Сохранить ключ"}</button>
            </div>
          </> : null}
      </div>

      {s.marketplace === "wb" && <div className="acc-box">
        <b>🔐 Ключи на запись: один или раздельно</b>
        <div className="hint">Для особо важных магазинов: основной ключ меняет всё, кроме цен (в нём <b>не должно</b> быть раздела «Цены и скидки»),
          а цены — только отдельным ключом с разделом «Цены и скидки». Утечка или ошибка с основным ключом не затронет цены; ключ для цен можно отозвать отдельно.</div>
        <div className="row">
          <label><input type="radio" disabled={!s.can_admin} checked={!s.split} onChange={() => http.put(`/api/shops/${shop}/actions/key_split`, { split: false })
            .then(() => { ok("Один ключ на запись"); load(); }).catch((e) => setErr(e.message))} /> Один ключ на запись (всё, включая цены)</label>
          <label><input type="radio" disabled={!s.can_admin} checked={s.split} onChange={() => http.put(`/api/shops/${shop}/actions/key_split`, { split: true })
            .then(() => { ok("Раздельные ключи включены"); load(); }).catch((e) => setErr(e.message))} /> Раздельно: основной + отдельный ключ для цен</label>
        </div>
        {s.split && <PriceKey shop={shop} s={s} onDone={(t) => { ok(t); load(); }} onErr={setErr} />}
      </div>}

      {s.blocks.map((b) => (
        <div key={b.key} className={"acc-box" + (b.soon ? " soon" : "")}>
          <div className="row"><b>{b.title}</b>{b.soon && <span className="chip">скоро</span>}
            {!b.soon && b.available && <label className="sw"><input type="checkbox" disabled={!s.can_admin} checked={b.enabled}
              onChange={(e) => saveBlock(b, e.target.checked, b.settings)} /> {b.enabled ? "включён" : "выключен"}</label>}</div>
          <div className="hint">{b.about}</div>
          {!b.soon && b.available && b.scope && wt && !b.scope_ok && <div className="err">В ключе на запись нет раздела «{b.scope}» — изменения этого блока не заработают.</div>}
          {b.key === "reviews" && b.available && <ReviewSettings b={b} s={s} onSave={(st) => saveBlock(b, b.enabled, st)} />}
          {b.key === "questions" && b.available && <QuestionSettings b={b} s={s} onSave={(st) => saveBlock(b, b.enabled, st)} />}
          {b.key === "ads" && b.available && <AdsSettings b={b} s={s} onSave={(st) => saveBlock(b, b.enabled, st)} />}
        </div>
      ))}

      <div className="acc-box">
        <b>📜 Журнал действий</b>
        {!s.log.length ? <div className="hint">Пока пусто.</div> : <table className="acc-t">
          <thead><tr><th>Когда</th><th>Кто</th><th>Что</th><th>Результат</th></tr></thead>
          <tbody>{s.log.map((l, i) => <tr key={i}><td>{dt(l.created_at)}</td><td>{l.by_ai ? "🤖 ИИ (авто)" : l.who || "сервис"}</td>
            <td>{l.action}{l.target ? ` · ${l.target}` : ""}</td><td>{l.ok ? "✅" : `❌ ${l.error || ""}`}</td></tr>)}</tbody></table>}
      </div>
    </div>
  );
}

function PriceKey({ shop, s, onDone, onErr }: { shop: number; s: St; onDone: (t: string) => void; onErr: (e: string) => void }) {
  const [tok, setTok] = useState("");
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const pt = typeof s.price_token === "object" ? s.price_token : null;
  return <div style={{ marginTop: 8 }}>
    <b>💰 Ключ для цен</b>
    {pt ? <>
      <div>Добавлен {dt(pt.added_at)}{pt.added_by ? ` (${pt.added_by})` : ""}{pt.exp ? `, действует до ${new Date(pt.exp).toLocaleDateString("ru-RU")}` : ""}</div>
      <div className="hint">Разделы: {pt.scopes.join(", ") || "—"}</div>
      {s.can_admin && <div><button onClick={() => { if (window.confirm("Удалить ключ для цен? Сервис не сможет менять цены.")) http.del(`/api/shops/${shop}/actions/write_token?purpose=prices`).then(() => onDone("Ключ для цен удалён")).catch((e) => onErr(e.message)); }}>Удалить ключ для цен</button></div>}
    </> : s.price_token === true ? <div>Ключ для цен добавлен (подробности видит админ).</div>
      : !s.can_admin ? <div className="hint">Ключ для цен не добавлен. Добавляет админ или владелец.</div> : <>
      <div className="hint">Отдельный ключ WB без галочки «Только чтение», с разделом «Цены и скидки» (лучше — только с ним). Того же кабинета продавца.</div>
      <div className="disclaimer">⚠️ {s.disclaimer.text}</div>
      <label><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} /> Понимаю и согласен: буду проверять и контролировать действия сервиса</label>
      <div className="row">
        <input type="password" className="tok-in" placeholder="Ключ API WB для цен" value={tok} onChange={(e) => setTok(e.target.value)} autoComplete="off" />
        <button className="pri" disabled={!agree || tok.length < 20 || busy} onClick={() => { setBusy(true);
          http.put(`/api/shops/${shop}/actions/write_token`, { token: tok, agree, version: s.disclaimer.version, purpose: "prices" })
            .then(() => { setTok(""); setAgree(false); onDone("Ключ для цен проверен и сохранён"); }).catch((e) => onErr(e.message)).finally(() => setBusy(false)); }}>
          {busy ? "Проверяю…" : "Сохранить ключ для цен"}</button>
      </div></>}
  </div>;
}

function ReviewSettings({ b, s, onSave }: { b: Block; s: St; onSave: (st: Block["settings"]) => void }) {
  const st = b.settings;
  const dis = !s.can_admin;
  const modeSel = (k: "pos_mode" | "neg_mode") => (
    <select disabled={dis} value={String(st[k])} onChange={(e) => onSave({ ...st, [k]: e.target.value })}>
      {s.modes.map((m) => <option key={m} value={m} disabled={(m === "draft" || m === "auto") && !s.ai.ok}>{MODE_T[m]}{(m === "draft" || m === "auto") && !s.ai.ok ? " (нужен тариф с ИИ)" : ""}</option>)}
    </select>);
  return <>
    {s.marketplace === "ozon" && <div className="disclaimer">ℹ️ Работа с отзывами через API Ozon доступна только с подпиской Ozon Premium Pro. Без неё отзывы не загружаются и ответы не отправляются.</div>}
    <div className="acc-row"><span>Отзывы 5★</span>{modeSel("pos_mode")}</div>
    <div className="acc-row"><span>Отзывы 4★ и ниже</span>{modeSel("neg_mode")}</div>
    {(st.pos_mode === "auto" || st.neg_mode === "auto") && <div className="acc-row"><span>Авто-ответов в сутки, не больше</span>
      <input type="number" min={0} max={500} disabled={dis} defaultValue={Number(st.auto_limit)} onBlur={(e) => onSave({ ...st, auto_limit: Number(e.target.value) })} /></div>}
    {(st.pos_mode === "auto" || st.neg_mode === "auto") && <div className="hint">ИИ сам отвечает только на отзывы, пришедшие после включения режима. Проверяйте ответы в разделе «Отзывы» → «Ответы сервиса» и оставляйте пометки, где ИИ ошибся.</div>}
    <div className="acc-row"><span>Сводка</span><label><input type="checkbox" disabled={dis} checked={!!st.notify_neg} onChange={(e) => onSave({ ...st, notify_neg: e.target.checked })} /> негативные отзывы за день — в ежедневной сводке (🔻 если упал рейтинг товара)</label></div>
    {s.marketplace === "wb" && <div className="acc-row"><span>Имя покупателя</span><label><input type="checkbox" disabled={dis} checked={!!st.use_name} onChange={(e) => onSave({ ...st, use_name: e.target.checked })} /> можно обращаться по имени (если в правилах выбран тон «по имени»; имя не хранится)</label></div>}
    {!s.ai.ok && <div className="hint">ИИ-режимы: {s.ai.reason}</div>}
    <div className="acc-row"><span>Советовать товары</span><label>в каждом <input type="number" min={1} max={20} disabled={dis} style={{ width: 60 }}
      defaultValue={Number(st.reco_every || 3)} onBlur={(e) => onSave({ ...st, reco_every: Number(e.target.value) })} />-м ответе (если в правилах включено «Советовать товары»)</label></div>
    {s.marketplace === "wb" && <div className="acc-row"><span>Регламент рекомендаций</span>
      <select disabled={dis} value={String(st.reco_reg || "")} onChange={(e) => onSave({ ...st, reco_reg: e.target.value })}>
        <option value="">Стандартный: по смыслу, рейтинг от 4,5</option>
        <option value="heat">Тепловое → сопутствующий → локомотив, рейтинг от 4,7, без замен (правило магазина)</option></select></div>}
    {st.reco_reg === "heat" && <div className="hint">Регламент (полностью — в «Базе знаний» → «Регламенты»): к нетепловому товару сначала тепловое
      оборудование (разных видов, по очереди), затем строго сопутствующий (аксессуар, расходник), затем товар-локомотив — тег «локомотив» в группах
      артикулов. К тепловому — только сопутствующий и локомотив. Замены и товары той же категории не советуем; рейтинг 4,6 и ниже — никогда.
      Действует и для вопросов.</div>}
    <div className="acc-row"><span>Замена при негативе</span><label><input type="checkbox" disabled={dis} checked={!!st.reco_neg_alt}
      onChange={(e) => onSave({ ...st, reco_neg_alt: e.target.checked })} /> в ответ на отзыв 4★ и ниже можно предложить замену (другой размер, объём), если она решает проблему</label></div>
    <div className="hint">Правила ответов (тон, что важно) — в разделе «⭐ Отзывы» → «Правила».</div>
  </>;
}

function QuestionSettings({ b, s, onSave }: { b: Block; s: St; onSave: (st: Block["settings"]) => void }) {
  const st = b.settings;
  const dis = !s.can_admin;
  return <>
    <div className="acc-row"><span>Ответы на вопросы</span>
      <select disabled={dis} value={String(st.mode)} onChange={(e) => onSave({ ...st, mode: e.target.value })}>
        {s.modes.map((m) => <option key={m} value={m} disabled={(m === "draft" || m === "auto") && !s.ai.ok}>{MODE_T[m]}{(m === "draft" || m === "auto") && !s.ai.ok ? " (нужен тариф с ИИ)" : ""}</option>)}
      </select></div>
    {st.mode === "auto" && <div className="acc-row"><span>Авто-ответов в сутки, не больше</span>
      <input type="number" min={0} max={500} disabled={dis} defaultValue={Number(st.auto_limit)} onBlur={(e) => onSave({ ...st, auto_limit: Number(e.target.value) })} /></div>}
    {st.mode === "auto" && <div className="hint">ИИ сам отвечает только на вопросы, пришедшие после включения режима. Проверяйте ответы в разделе «Вопросы» → «Ответы сервиса» и оставляйте пометки, где ИИ ошибся.</div>}
    {!s.ai.ok && <div className="hint">ИИ-режимы: {s.ai.reason}</div>}
    <div className="acc-row"><span>Советовать товары</span><label>в каждом <input type="number" min={1} max={20} disabled={dis} style={{ width: 60 }}
      defaultValue={Number(st.reco_every || 3)} onBlur={(e) => onSave({ ...st, reco_every: Number(e.target.value) })} />-м ответе (если в правилах включено «Советовать товары»)</label></div>
    <div className="hint">Правила ответов (тон, факты о товарах) — в разделе «❓ Вопросы» → «Правила».</div>
  </>;
}

/** Пороги правил рекламы (ads_ai): что считать убытком, когда товар «кончается», шаг ставки, лимит пополнения бюджета. */
function AdsSettings({ b, s, onSave }: { b: Block; s: St; onSave: (st: Block["settings"]) => void }) {
  const st = b.settings;
  const dis = !s.can_admin;
  const num = (k: string, label: string, hint: string) => (
    <div className="acc-row"><span>{label}</span>
      <input type="number" disabled={dis} defaultValue={Number(st[k])} style={{ width: 110 }} onBlur={(e) => Number(e.target.value) !== Number(st[k]) && onSave({ ...st, [k]: Number(e.target.value) })} />
      <span className="hint">{hint}</span></div>);
  return <>
    {num("window_days", "Окно решений, дней", "по скольким дням считать прибыль рекламы (по 3 дням — шум; срочное «кликов много, ни заказов, ни корзин» — всё равно по 3)")}
    {num("loss_min_spend", "Расход от, ₽", "за окно: меньше (и меньше двух безубыточных заказов и 30 кликов) — денежные правила не срабатывают, мало данных")}
    {num("loss_weeks", "Пауза после убыточных окон", "столько окон подряд реклама заметно в минусе, а снижение ставки уже не помогло — предложить паузу (вне сезона — после одного)")}
    {num("cooldown_h", "Пауза между изменениями, ч", "после изменения кампании (кнопкой или вручную в кабинете) её ставки не трогаем столько часов — пусть итог проявится")}
    {num("max_step", "Шаг ставки до, %", "снижение по глубине убытка: реклама на заказ в 2+ раза дороже безубыточной — −30 %, в 1,2–2 — −20 %, иначе −10 % (не больше этого шага); больше за раз — с двойным подтверждением")}
    {num("up_stock_days", "Повышать ставку, если товара на, дней", "повышение — только когда заказ из рекламы дешевле половины безубыточного за всё окно и товара хватает на столько дней; +10 % за раз")}
    {num("stock_days_min", "Товар кончается, дней", "остатка меньше чем на столько дней — пауза рекламы")}
    {num("kw_min_clicks", "Ключ без заказов, кликов от", "в минус-фразы — не раньше, чем кликов станет 3 ÷ конверсия склейки в заказ (и не меньше этого числа) и потрачен один безубыточный заказ")}
    {num("deposit_max", "Пополнение бюджета до, ₽", "за одно предложение; всегда с двойным подтверждением. Часто встающим на паузу выгодным кампаниям — на неделю")}
    {num("season_loss_pct", "Сезонный разгон: минус до, % расхода", "в сезон и за месяц до него рекламу в небольшом минусе не останавливаем, если органика растёт")}
    {num("season_organic_pct", "…если органика выросла на, %", "заказы без рекламы за окно против прошлого окна")}
    <div className="acc-row"><span>Сезоны по предметам</span>
      <textarea disabled={dis} rows={3} style={{ width: 360 }} defaultValue={String(st.seasons || "")} placeholder={"обогреватели: 10,11,12,1,2,3\nсвечи: 10,11,12"}
        onBlur={(e) => e.target.value !== String(st.seasons || "") && onSave({ ...st, seasons: e.target.value })} />
      <span className="hint">строка — «часть названия предмета: месяцы сезона»; «предмет: -» — без сезона. Встроены: обогрев, пушки, конвекторы, завесы, снегоуборщики, гирлянды, триммеры, газонокосилки и др.</span></div>
    <div className="acc-row"><span>Менеджеры</span>
      <input disabled={dis} style={{ width: 360 }} defaultValue={String(st.managers || "")} placeholder="Алена, Лера, Кристина"
        onBlur={(e) => e.target.value !== String(st.managers || "") && onSave({ ...st, managers: e.target.value })} />
      <span className="hint">имена через запятую — итоги рекламы по менеджерам ищут имя в названии кампании (частые имена узнаются и без списка)</span></div>
    <div className="acc-row"><span>Новые кампании</span><label><input type="checkbox" disabled={dis} checked={st.create !== false}
      onChange={(e) => onSave({ ...st, create: e.target.checked })} /> предлагать создать кампанию для хорошо продающихся склеек без рекламы</label></div>
    <div className="acc-row"><span>Уведомления</span><label><input type="checkbox" disabled={dis} checked={st.notify !== false}
      onChange={(e) => onSave({ ...st, notify: e.target.checked })} /> присылать в бот «Стометрик», когда появились новые предложения</label></div>
    <div className="hint">Предложения и кнопки «Применить» — в разделе «📢 Реклама».</div>
  </>;
}
