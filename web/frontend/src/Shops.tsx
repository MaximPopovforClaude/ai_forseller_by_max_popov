import { useEffect, useState } from "react";
import { api, type WorkspaceInfo } from "./api";

const d = (s: string | null | undefined) => (s ? new Date(s).toLocaleDateString("ru-RU") : "—");
const dt = (s: string | null) => (s ? new Date(s).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" }) : "—");

/** Магазины кабинета: добавить с ключом API, заменить ключ, ход первой загрузки. Ключ обратно не показывается никогда. */
const MP: Record<string, string> = { wb: "Wildberries", ozon: "Ozon", ym: "Яндекс Маркет" };

export function Shops({ w, reload, onShopsChanged }: { w: WorkspaceInfo; reload: () => void; onShopsChanged: () => void }) {
  const isAdmin = w.role === "owner" || w.role === "admin";
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [repl, setRepl] = useState<number | null>(null);
  const [newTok, setNewTok] = useState("");
  const [mp, setMp] = useState<"wb" | "ozon" | "ym">("wb");
  const [clientId, setClientId] = useState("");
  const [adId, setAdId] = useState("");
  const [adSecret, setAdSecret] = useState("");
  const [adRepl, setAdRepl] = useState<number | null>(null);
  const total = (s: WorkspaceInfo["shops"][number]) => s.load_total ?? w.first_load_total;
  const loading = w.shops.some((s) => s.loaded < total(s));
  useEffect(() => { if (!loading) return; const t = setInterval(reload, 30000); return () => clearInterval(t); }, [loading]); // eslint-disable-line react-hooks/exhaustive-deps

  const status = (s: WorkspaceInfo["shops"][number]) => {
    if (!s.is_active) return "выключен";
    if (s.loaded < total(s)) return `загрузка истории: ${s.loaded} из ${total(s)} разделов`;
    return `обновлено ${dt(s.last_ok)}`;
  };
  const exp = (s: WorkspaceInfo["shops"][number]) => {
    if (!s.token) return s.token_server ? "на сервере" : "—";
    if (s.marketplace === "ym") return <span title={(s.token.scopes || []).join(", ")}>кабинет {s.token.seller_oid}{s.token.read_only ? ", только чтение" : ""}</span>;
    if (s.marketplace === "ozon") return <span title={(s.token.roles || []).join(", ")}>Client-Id {s.token.seller_oid}{s.token.roles?.length ? `, роли: ${s.token.roles.join(", ")}` : ""}
      <div className="hint">{s.ad_token ? `Реклама: ключ с ${d(s.ad_token.added_at)}, кампаний ${s.ad_token.campaigns ?? "?"} (активных ${s.ad_token.running ?? "?"})` : "Реклама: ключ не добавлен"}</div></span>;
    const days = s.token.exp ? Math.round((new Date(s.token.exp).getTime() - Date.now()) / 864e5) : null;
    return <span className={days !== null && days < 14 ? "down" : ""} title={s.token.scopes.join(", ")}>{s.token.kind}, до {d(s.token.exp)}{days !== null && days < 14 ? ` (осталось ${days} дн.)` : ""}</span>;
  };
  return (
    <div className="acc-box">
      <b>Магазины кабинета</b>
      {err && <div className="err">{err}</div>}
      {ok && <div className="ok">{ok}</div>}
      {warnings.map(message => <div key={message} className="disclaimer" role="status">⚠️ {message}</div>)}
      <table className="acc-t">
        <thead><tr><th>Магазин</th><th>Площадка</th><th>Статус</th>{isAdmin && <th>Ключ API</th>}{isAdmin && <th />}</tr></thead>
        <tbody>{w.shops.map((s) => (
          <tr key={s.id}>
            <td>{s.title || s.name}{s.token?.seller_oid ? <div className="hint">кабинет {MP[s.marketplace] || "WB"} {s.token.seller_oid}</div> : null}</td>
            <td>{MP[s.marketplace] || "Wildberries"}</td>
            <td>{status(s)}</td>
            {isAdmin && <td>{exp(s)}</td>}
            {isAdmin && <td className="acts">
              {repl === s.id ? <>
                <input type="password" className="tok-in" placeholder={s.marketplace === "ozon" ? "Новый Api-Key Ozon" : s.marketplace === "ym" ? "Новый Api-Key Маркета" : "Новый ключ API"} value={newTok} onChange={(e) => setNewTok(e.target.value)} autoComplete="off" />
                <button className="pri" disabled={busy || newTok.length < 20} onClick={() => { setBusy(true); setErr(""); setOk(""); setWarnings([]);
                  api.replaceToken(s.id, newTok).then((r) => { setOk("Ключ заменён"); setWarnings(r.warnings || []); setRepl(null); setNewTok(""); reload(); })
                    .catch((e) => setErr(e.message)).finally(() => setBusy(false)); }}>{busy ? "Проверяю…" : "Сохранить"}</button>
                <button onClick={() => { setRepl(null); setNewTok(""); }}>Отмена</button>
              </> : adRepl === s.id ? <>
                <input className="tok-in" placeholder="Client ID рекламы" value={adId} onChange={(e) => setAdId(e.target.value.trim())} autoComplete="off" />
                <input type="password" className="tok-in" placeholder="Client Secret" value={adSecret} onChange={(e) => setAdSecret(e.target.value.trim())} autoComplete="off" />
                <button className="pri" disabled={busy || !adId || !adSecret} onClick={() => { setBusy(true); setErr("");
                  api.replaceAdToken(s.id, adId, adSecret).then((r) => { setOk(`Рекламный ключ сохранён: кампаний ${r.campaigns}, активных ${r.running}. Статистика подтянется в течение 10–20 минут.`); setAdRepl(null); setAdId(""); setAdSecret(""); reload(); })
                    .catch((e) => setErr(e.message)).finally(() => setBusy(false)); }}>{busy ? "Проверяю…" : "Сохранить"}</button>
                <button onClick={() => { setAdRepl(null); setAdId(""); setAdSecret(""); }}>Отмена</button>
              </> : <>
                <button onClick={() => { setRepl(s.id); setNewTok(""); }}>Заменить ключ</button>
                {s.marketplace === "ozon" && <button onClick={() => { setAdRepl(s.id); setAdId(""); setAdSecret(""); setOk(""); }}>{s.ad_token ? "Заменить ключ рекламы" : "Ключ рекламы"}</button>}
              </>}
            </td>}
          </tr>
        ))}</tbody>
      </table>
      {isAdmin && !adding && <button className="pri add-shop" onClick={() => { setAdding(true); setOk(""); }}>+ Добавить магазин</button>}
      {isAdmin && adding && (
        <div className="add-box">
          <div className="acc-row"><span>Название</span><input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Например: ИП Иванов / бренд" /></div>
          <div className="acc-row"><span>Площадка</span><select value={mp} onChange={(e) => setMp(e.target.value as "wb" | "ozon" | "ym")}><option value="wb">Wildberries</option><option value="ozon">Ozon</option><option value="ym">Яндекс Маркет</option></select></div>
          {mp === "ozon" && <div className="acc-row"><span>Client-Id</span><input value={clientId} onChange={(e) => setClientId(e.target.value.replace(/\D/g, ""))} inputMode="numeric" placeholder="Число из ЛК Ozon" /></div>}
          <div className="acc-row"><span>{mp === "wb" ? "Ключ API" : "Api-Key"}</span><input type="password" className="tok-in" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" placeholder="Вставьте ключ" /></div>
          {mp === "ozon" && <>
            <div className="acc-row"><span>Реклама: Client ID</span><input value={adId} onChange={(e) => setAdId(e.target.value.trim())} autoComplete="off" placeholder="Необязательно, можно добавить позже" /></div>
            <div className="acc-row"><span>Реклама: Client Secret</span><input type="password" className="tok-in" value={adSecret} onChange={(e) => setAdSecret(e.target.value.trim())} autoComplete="off" placeholder="Необязательно" /></div>
          </>}
          {mp === "ozon" ? <div className="hint">
            Где взять: личный кабинет Ozon → Настройки → Seller API. Client-Id — число вверху страницы; Api-Key — «Сгенерировать ключ»,
            роль лучше «Admin read only» (только чтение: товары, цены, остатки, отправления, финансы, аналитика). Ключ хранится
            зашифрованным и больше нигде не показывается.<br />
            Реклама Ozon — отдельный ключ (Performance API): Ozon → Продвижение → Настройки → API → «Создать аккаунт» → Client ID и Client Secret.
            Без него расходы на рекламу видны только итогом из начислений, без кампаний, показов и кликов.
          </div> : mp === "ym" ? <div className="hint">
            Где взять: кабинет Яндекс Маркета → Настройки → API и модули → «Создать новый токен». Доступ — «Все методы — только чтение»
            (или чтение заказов, цен, каталога и финансов). Сервис сам найдёт все магазины кабинета (FBY, FBS, DBS). Ключ хранится
            зашифрованным и больше нигде не показывается.
          </div> : <div className="hint">
            Где взять: личный кабинет WB → Профиль → Настройки → Доступ к API → «Создать токен». Тип — «Персональный» или «Сервисный»
            (не «Базовый»), разделы: Контент, Аналитика, Цены и скидки, Статистика, Продвижение, Финансы, Поставки; можно «Только чтение».
            Ключ хранится зашифрованным и больше нигде не показывается.
          </div>}
          <div className="acc-row"><span />
            <button className="pri" disabled={busy || !title.trim() || token.length < 20 || (mp === "ozon" && (!clientId || !adId !== !adSecret))} onClick={() => { setBusy(true); setErr(""); setOk(""); setWarnings([]);
              api.addShop(w.id, { title, token, marketplace: mp, client_id: mp === "ozon" ? clientId : undefined,
                ad_client_id: mp === "ozon" && adId ? adId : undefined, ad_client_secret: mp === "ozon" && adSecret ? adSecret : undefined }).then((r) => {
                setOk(r.first_load ? "Магазин добавлен — грузим историю (обычно около часа); таблицы наполняются по ходу." : "Магазин добавлен — история догрузится автосбором в течение пары часов.");
                setWarnings(r.warnings || []);
                setAdding(false); setTitle(""); setToken(""); setClientId(""); setAdId(""); setAdSecret(""); reload(); onShopsChanged();
              }).catch((e) => setErr(e.message)).finally(() => setBusy(false)); }}>{busy ? "Проверяю ключ…" : "Добавить"}</button>
            <button onClick={() => { setAdding(false); setToken(""); setAdId(""); setAdSecret(""); }}>Отмена</button>
          </div>
        </div>
      )}
    </div>
  );
}
