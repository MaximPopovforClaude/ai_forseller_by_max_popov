import { useRef, useState } from "react";

/** Над листом «Себестоимость»: загрузка файлом или ссылкой на Google-таблицу, фильтр «не задана» . */
type Res = { updated: number; same: number; unknown: number; unknown_list: string[]; bad: number; total: number; valid_from: string; by: string };

export function CostBar({ shop, missing, total, onlyMissing, setOnlyMissing, onDone }: {
  shop: number; missing: number; total: number; onlyMissing: boolean; setOnlyMissing: (v: boolean) => void; onDone: () => void }) {
  const today = new Date().toISOString().slice(0, 10);
  const [vf, setVf] = useState(today);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const file = useRef<HTMLInputElement>(null);
  const done = (j: Res) => {
    const d = `${j.valid_from.slice(8, 10)}.${j.valid_from.slice(5, 7)}.${j.valid_from.slice(0, 4)}`;
    setMsg(`Готово (по ${j.by}): обновлено ${j.updated}, без изменений ${j.same}` + (j.unknown ? `, не нашли в магазине ${j.unknown}` +
      (j.unknown_list.length ? ` (${j.unknown_list.slice(0, 5).join(", ")}${j.unknown > 5 ? "…" : ""})` : "") : "") +
      (j.bad ? `, странных значений ${j.bad}` : "") + `. Действует с ${d}.`);
    onDone();
  };
  const run = async (p: Promise<Response>) => {
    setErr(""); setMsg(""); setBusy(true);
    try {
      const r = await p; const j = await r.json();
      if (!r.ok) throw new Error(j.detail || r.statusText);
      done(j);
    } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const q = `valid_from=${vf}`;
  return (
    <div className="acc-box cost-bar">
      <div className="rnp-bar">
        <label className="chk"><input type="checkbox" checked={onlyMissing} onChange={(e) => setOnlyMissing(e.target.checked)} />
          {" "}только без себестоимости ({missing} из {total})</label>
        <label>Действует с <input type="date" value={vf} onChange={(e) => setVf(e.target.value || today)} /></label>
        <input ref={file} type="file" accept=".xlsx,.csv" hidden onChange={(e) => {
          const f = e.target.files?.[0]; e.target.value = "";
          if (f) run(fetch(`/api/shops/${shop}/cost/import?name=${encodeURIComponent(f.name)}&${q}`, { method: "POST", body: f,
            credentials: "same-origin", headers: { "Content-Type": "application/octet-stream" } }));
        }} />
        <button disabled={busy} onClick={() => file.current?.click()}>⬆ Загрузить файл (xlsx, csv)</button>
        <input placeholder="или ссылка на Google-таблицу" value={url} onChange={(e) => setUrl(e.target.value)} style={{ minWidth: 300 }} />
        <button disabled={busy || !url.trim()} onClick={() => run(fetch(`/api/shops/${shop}/cost/import_url`, { method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url: url.trim(), valid_from: vf }) }))}>
          {busy ? "Загружаю…" : "Загрузить по ссылке"}</button>
        {msg && <span className="ok">{msg}</span>}
      </div>
      {err && <div className="err">{err}</div>}
      <div className="hint">В файле или таблице нужны столбец артикула («Артикул WB», nmId или SKU — либо «Артикул продавца») и столбец «Себестоимость».
        Google-таблица — с доступом «Все, у кого есть ссылка». Новая цена пишется с датой «Действует с», прошлые периоды не пересчитываются.
        Изменить одну — двойной клик по ячейке.</div>
    </div>
  );
}
