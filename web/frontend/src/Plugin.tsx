import { useState } from "react";
import { http } from "./api";
import { copyCell } from "./copy";

/** Плагин Chrome : скачать, получить код для входа (показывается один раз; новый код отключает старый). */
export function PluginBox({ wsId, wsName }: { wsId: number; wsName: string }) {
  const [tok, setTok] = useState(""), [err, setErr] = useState(""), [busy, setBusy] = useState(false);
  const get = () => {
    if (!confirm("Получить новый код плагина? Старый код (если был) перестанет работать.")) return;
    setBusy(true); setErr("");
    http.post<{ token: string }>("/api/plugin/token", { workspace_id: wsId })
      .then((r) => setTok(r.token)).catch((e) => setErr(e.message)).finally(() => setBusy(false));
  };
  return (
    <div className="acc-box">
      <b>🧩 Плагин Chrome для Wildberries</b>
      <div className="hint">На карточках WB — полки (у кого в полках товар и кто в полке у него), наши цифры по своим товарам.
        В кабинете продавца — автоскачивание отчётов «Точки входа» (настраивается).</div>
      <div className="hint">Доступен на любом тарифе. Код для кабинета «{wsName}» даёт доступ только к разрешённым вам магазинам.
        Для загрузки отчётов нужна роль «Редактор» или выше.</div>
      <ol className="hint" style={{ margin: "6px 0", paddingLeft: 18 }}>
        <li>Скачайте архив и распакуйте его в папку, которую не будете удалять.</li>
        <li>Chrome → chrome://extensions → включите «Режим разработчика» → «Загрузить распакованное» → выберите папку seller-analytics-plugin.</li>
        <li>Нажмите значок плагина (пазл → seller-analytics), вставьте код и нажмите «Подключить».</li>
      </ol>
      <a className="btn" href="/api/plugin/download"><button>⬇ Скачать плагин</button></a>{" "}
      <button disabled={busy} onClick={get}>🔑 Получить код</button>
      {tok && <div style={{ marginTop: 8 }}>
        <div className="hint">Код показывается один раз — скопируйте и вставьте в плагин. Никому не пересылайте.</div>
        <code style={{ wordBreak: "break-all", cursor: "pointer" }} onClick={(e) => copyCell(tok, e.nativeEvent)}>{tok}</code>
      </div>}
      {err && <div className="err">{err}</div>}
    </div>
  );
}
