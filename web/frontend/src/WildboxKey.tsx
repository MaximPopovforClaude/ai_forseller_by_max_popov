import { useEffect, useRef, useState } from "react";
import { http } from "./api";
import { describeAiAccess, type AiAccess } from "./aiAccess";

type Prov = { id: string; title: string; model: string; keys: string };
type St = AiAccess & { connected: boolean; added_at: string | null; who: string | null; can_edit: boolean; plan?: string;
  provider?: string | null; model?: string | null; providers?: Prov[] };

const KINDS = {
  openai_images: { title: "GPT Image · OpenAI API", name: "OpenAI для изображений", hint: "Для отрисовки и доработки фото в «Визуале» напрямую через GPT Image 2.5 Sunburst. "
    + "Введите API-ключ OpenAI с доступом к изображениям и чтению моделей. Используется счёт OpenAI API, отдельно от лимитов подписки ChatGPT. "
    + "Оплачивает владелец ключа; редакторы магазинов этого аккаунта смогут запускать генерацию. Фото и задание передаются OpenAI только при запуске. "
    + "Проверка ключа бесплатная, без генерации. Для рисования могут потребоваться баланс API и верификация организации OpenAI." },
  wildbox: { title: "Wildbox", name: "Wildbox", hint: "Нужен для вкладок «Конкуренты», «МониторингКонкурентов» и разделов ИИ-сводки про конкурентов и нишу: "
    + "данные рынка берутся по вашему тарифу Wildbox. Ключ — в личном кабинете Wildbox (раздел API / MCP)." },
  claude: { title: "Нейросеть", name: "нейросети", hint: "Свой ключ нейросети — Claude, ChatGPT, Gemini или DeepSeek: она пишет ИИ-сводку на главной, "
    + "разбор дня, отвечает в Стометрике, готовит черновики отзывов и карточек. Цифры считает сервис, нейросеть только объясняет. "
    + "Нейросеть ничего не меняет в сервисе и кабинете: у неё доступ только на чтение, любые изменения — черновиком, записываете вы кнопкой. "
    + "Расход — по вашему счёту у выбранной нейросети." },
} as const;

/** Ключ кабинета (Wildbox / нейросеть). Хранится зашифрованным, обратно не показывается. */
export function SecretKey({ wsId, kind }: { wsId: number; kind: keyof typeof KINDS }) {
  const K = KINDS[kind];
  const [st, setSt] = useState<St | null>(null);
  const [tok, setTok] = useState("");
  const [prov, setProv] = useState("anthropic");
  const [model, setModel] = useState("");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const generation = useRef(0);
  const load = () => {
    const current = generation.current;
    return http.get<St>(`/api/workspaces/${wsId}/secret/${kind}`)
      .then((value) => { if (generation.current === current) setSt(value); })
      .catch((e) => { if (generation.current === current) setErr(e.message); });
  };
  useEffect(() => {
    generation.current += 1;
    setSt(null); setErr(""); setOk(""); setTok(""); setOpen(false);
    void load();
    return () => { generation.current += 1; };
  }, [wsId, kind]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!st) return err ? <div className="err">{err}</div> : null;
  if (kind === "claude" && (st.ai_route !== "workspace_api" || !st.can_edit)) {
    const access = describeAiAccess(st);
    return (
    <div className="acc-box">
      <b>{K.title}</b>
      <div className="acc-row"><span>Статус</span>{access.status}</div>
      <div className="hint">{access.detail}</div>
    </div>
    );
  }
  const save = () => {
    setBusy(true); setErr("");
    http.put(`/api/workspaces/${wsId}/secret/${kind}`, kind === "claude" ? { token: tok, provider: prov, model: model.trim() || null } : { token: tok }).then(() => { setTok(""); setOpen(false); setOk(`Ключ ${K.name} подключён`); load(); })
      .catch((e) => setErr(e.message)).finally(() => setBusy(false));
  };
  return (
    <div className="acc-box">
      <b>{K.title}</b>
      <div className="hint">{K.hint} Храним зашифрованным, никому не показываем.</div>
      {kind === "openai_images" && <div className="hint"><a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer">Создать ключ OpenAI</a>{" · "}
        <a href="https://platform.openai.com/usage" target="_blank" rel="noreferrer">Расход API</a>{" · "}
        <a href="https://developers.openai.com/api/docs/pricing" target="_blank" rel="noreferrer">Тарифы OpenAI</a></div>}
      <div className="acc-row"><span>Статус</span>
        {st.connected ? <>✓ подключён{st.provider ? ` — ${st.providers?.find((p) => p.id === st.provider)?.title ?? st.provider}, модель ${st.model}` : ""}{st.added_at ? ` ${new Date(st.added_at).toLocaleDateString("ru-RU")}` : ""}{st.who ? ` (${st.who})` : ""}</> : "не подключён"}
      </div>
      {st.can_edit && (open || !st.connected) && st.providers && <>
        <div className="acc-row"><span>Нейросеть</span>
          <select value={prov} onChange={(e) => { setProv(e.target.value); setModel(""); }}>
            {st.providers.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
          </select>
          <input value={model} onChange={(e) => setModel(e.target.value)} placeholder={`модель: ${st.providers.find((p) => p.id === prov)?.model ?? ""}`} style={{ width: 200 }} />
        </div>
        <div className="hint">Ключ: {st.providers.find((p) => p.id === prov)?.keys}. Модель можно не указывать — возьмём рекомендованную.</div>
      </>}
      {st.can_edit && (open || !st.connected ? (
        <div className="acc-row"><span>Ключ</span>
          <input type="password" autoComplete="off" value={tok} onChange={(e) => setTok(e.target.value)} placeholder={`вставьте ключ ${K.name}`} style={{ flex: 1, minWidth: 220 }} />
          <button disabled={busy || !tok.trim()} onClick={save}>{busy ? "Проверяю…" : "Сохранить"}</button>
          {open && <button className="link" onClick={() => setOpen(false)}>отмена</button>}
        </div>
      ) : (
        <div className="acc-row"><span></span>
          <button onClick={() => setOpen(true)}>Заменить ключ</button>
          <button className="link" onClick={() => confirm(`Отключить ${K.name} от кабинета?`)
            && http.del(`/api/workspaces/${wsId}/secret/${kind}`).then(() => { setOk(`${K.name} отключён`); load(); }).catch((e) => setErr(e.message))}>отключить</button>
        </div>
      ))}
      {ok && <div className="ok">{ok}</div>}
      {err && <div className="err">{err}</div>}
    </div>
  );
}

/** Аккаунт Higgsfield (раздел «Визуал»): вход на higgsfield.ai — сервис рисует слайды по тарифу и кредитам клиента, все модели (Nano Banana, GPT Image…). */
export function HiggsfieldConnect({ wsId }: { wsId: number }) {
  type H = { connected: boolean; added_at: string | null; who: string | null; email: string | null; can_edit: boolean };
  const [st, setSt] = useState<H | null>(null);
  const [err, setErr] = useState("");
  const load = () => http.get<H>(`/api/workspaces/${wsId}/higgsfield`).then(setSt).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [wsId]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!st) return null;
  const connect = () => http.post<{ url: string }>(`/api/workspaces/${wsId}/higgsfield/connect`).then((r) => { window.location.href = r.url; }).catch((e) => setErr(e.message));
  const back = new URLSearchParams(window.location.search).get("hf");
  return (
    <div className="acc-box">
      <b>Higgsfield (отрисовка слайдов)</b>
      <div className="hint">Для раздела «Визуал»: нейросети (Nano Banana Pro / 2, GPT Image 2.5, Seedream) рисуют слайды карточки по согласованному ТЗ —
        через ваш аккаунт Higgsfield, по вашему тарифу и кредитам. Рисуем только по вашему нажатию «Рисовать», стоимость в кредитах показываем заранее.
        Пароль от Higgsfield сервис не видит: вход — на сайте Higgsfield.</div>
      <div className="acc-row"><span>Статус</span>{st.connected ? <>✓ подключён{st.email ? ` — ${st.email}` : ""}{st.added_at ? ` ${new Date(st.added_at).toLocaleDateString("ru-RU")}` : ""}{st.who ? ` (${st.who})` : ""}</> : "не подключён"}</div>
      {back === "ok" && <div className="ok">Аккаунт Higgsfield подключён</div>}
      {back === "error" && <div className="err">Не удалось подключить Higgsfield — попробуйте ещё раз</div>}
      {st.can_edit && <div className="acc-row"><span></span>
        <button className={st.connected ? "" : "pri"} onClick={connect}>{st.connected ? "Переподключить" : "Подключить аккаунт Higgsfield"}</button>
        {st.connected && <button className="link" onClick={() => confirm("Отключить Higgsfield от кабинета?") && http.del(`/api/workspaces/${wsId}/higgsfield`).then(load).catch((e) => setErr(e.message))}>отключить</button>}
      </div>}
      {err && <div className="err">{err}</div>}
    </div>
  );
}
