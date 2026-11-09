import { useState } from "react";
import { http } from "./api";
import { copyCell } from "./copy";

/** Плагин Chrome : скачать, получить код для входа (показывается один раз; новый код отключает старый). */
export function PluginBox({ wsId, wsName }: { wsId: number; wsName: string }) {
  const [tok, setTok] = useState(""), [err, setErr] = useState(""), [busy, setBusy] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const download = async () => {
    setDownloading(true); setErr("");
    try {
      const response = await fetch("/api/plugin/download", { credentials: "same-origin" });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === "string" ? data.detail : "Архив не подготовлен. Проверьте адрес сайта в настройках установки.");
      }
      if (!response.headers.get("content-type")?.includes("application/zip")) throw new Error("Сайт не вернул архив плагина. Проверьте настройку HTTPS-прокси.");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a"); link.href = url; link.download = "seller-analytics-plugin.zip";
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setErr((e as Error).message); }
    finally { setDownloading(false); }
  };
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
        <li>Скачайте архив с этого сайта: адрес вашей платформы уже настроен. Распакуйте в постоянную папку.</li>
        <li>Chrome → chrome://extensions → включите «Режим разработчика» → «Загрузить распакованное» → выберите папку seller-analytics-plugin.</li>
        <li>Нажмите значок плагина (пазл → AI-100metric by Max Popov), вставьте код и нажмите «Подключить».</li>
      </ol>
      <button disabled={downloading} onClick={download}>{downloading ? "Готовлю архив…" : "⬇ Скачать плагин"}</button>{" "}
      <button disabled={busy} onClick={get}>🔑 Получить код</button>
      <div className="hint">После обновления замените файлы в прежней папке расширения, перезагрузите его в Chrome и обновите вкладки WB. Версия 0.2.9; код нужно ввести заново.</div>
      {tok && <div style={{ marginTop: 8 }}>
        <div className="hint">Код показывается один раз — скопируйте и вставьте в плагин. Никому не пересылайте.</div>
        <code style={{ wordBreak: "break-all", cursor: "pointer" }} onClick={(e) => copyCell(tok, e.nativeEvent)}>{tok}</code>
      </div>}
      {err && <div className="err">{err}</div>}
    </div>
  );
}
