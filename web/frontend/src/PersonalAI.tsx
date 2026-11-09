import { useEffect, useRef, useState } from "react";
import { http } from "./api";

type Ready = { text_ready?: boolean; image_ready?: boolean; reason?: string; image_reason?: string; model?: string };
type Config = Ready & { workspace_id?: number; shop_ids?: number[]; enabled?: boolean; checked_at?: string };
type State = { config: Config; workspaces: { id: number; name: string }[]; shops: { id: number; title: string; name: string; workspace_id: number }[] };

export function PersonalAI({ onSaved }: { onSaved: () => void }) {
  const [data, setData] = useState<State | null>(null);
  const [ws, setWs] = useState(0);
  const [shops, setShops] = useState<number[]>([]);
  const [ready, setReady] = useState<Ready | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const live = useRef(false);
  useEffect(() => {
    live.current = true;
    http.get<State>("/api/admin/personal-ai").then(d => {
      if (!live.current) return;
      setData(d); setWs(d.config.workspace_id || d.workspaces[0]?.id || 0); setShops(d.config.shop_ids || []);
    }).catch(e => { if (live.current) setError(e.message); });
    return () => { live.current = false; };
  }, []);
  async function check() {
    setBusy(true); setError(""); setReady(null);
    try {
      const result = await http.post<Ready>("/api/admin/personal-ai/check");
      if (live.current) setReady(result);
    } catch (e) { if (live.current) setError((e as Error).message); }
    finally { if (live.current) setBusy(false); }
  }
  async function save(enabled: boolean) {
    setBusy(true); setError("");
    try {
      const result = await http.put<{ config: Config }>("/api/admin/personal-ai", { workspace_id: ws, shop_ids: shops, enabled });
      if (!live.current) return;
      setData(d => d ? { ...d, config: result.config } : d); setReady(null); onSaved();
    } catch (e) { if (live.current) setError((e as Error).message); }
    finally { if (live.current) setBusy(false); }
  }
  const status = ready || data?.config;
  return <section className="acc-box" aria-label="Личная подписка владельца">
    <h3>VIP · личная подписка ChatGPT владельца</h3>
    <p>Аналитика, задачи и Стометрик на сайте и в Telegram работают через твой личный ChatGPT. GPT Image использует доступные лимиты той же подписки.</p>
    <p>Доступ только владельцу установки в выбранных своих магазинах. Для сторонних клиентов используются отдельные API-ключи.</p>
    <p>Сначала установи Codex и выполни личный вход на сервере по <a href="https://github.com/MaximPopovforClaude/ai_forseller_by_max_popov/blob/main/docs/PERSONAL-AI.md" target="_blank" rel="noreferrer">инструкции подключения</a>. Коды входа и токены на сайт вводить не нужно.</p>
    {error && <div className="err" role="alert">{error}</div>}
    {!data && !error && <p>Загрузка настроек…</p>}
    {data && <>
      <p>VIP {data.config.enabled ? "включён" : "выключен"}. {data.config.checked_at && `Последняя проверка: ${new Date(data.config.checked_at).toLocaleString("ru-RU")}.`}</p>
      <fieldset disabled={busy}>
        <label>Свой кабинет <select aria-label="Свой кабинет" value={ws} onChange={e => { setWs(Number(e.target.value)); setShops([]); }}>
          {!data.workspaces.length && <option value={0}>Нет своего кабинета</option>}
          {data.workspaces.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
        </select></label>
        <p>Отметь только магазины, которые принадлежат тебе:</p>
        {data.shops.filter(s => s.workspace_id === ws).map(s => <label key={s.id} style={{ display: "block" }}>
          <input type="checkbox" checked={shops.includes(s.id)} onChange={e => setShops(v => e.target.checked ? [...v, s.id] : v.filter(id => id !== s.id))} /> {s.title || s.name}
        </label>)}
        <button onClick={check}>Проверить подключение</button>
        <button disabled={!ws || !shops.length || !ready?.text_ready} onClick={() => save(true)}>Включить VIP / сохранить выбор</button>
        {data.config.enabled && <button onClick={() => save(false)}>Выключить личный ИИ</button>}
      </fieldset>
      {busy && <p role="status">Проверяем подключение или сохраняем настройки…</p>}
      {status && <div role="status">
        <p>Стометрик и аналитика: {status.text_ready ? "доступны" : "не подтверждены"}. {status.reason}</p>
        <p>GPT Image: {status.image_ready ? "доступен" : "не подтверждён"}. {status.image_reason}</p>
      </div>}
      <p className="hint">Проверка не запускает генерацию. При исчерпании лимита запрос останавливается; автоматического перехода на платный API нет. Фоновые задачи расходуют лимиты после включения соответствующих блоков магазина.</p>
    </>}
  </section>;
}
