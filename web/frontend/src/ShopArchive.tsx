import { useRef, useState } from "react";
import { http } from "./api";

export type ArchiveShop = { id: number; name: string; title: string | null; workspace: string | null;
  marketplace: string; archived_at: string | null; archived_was_active: boolean | null };

export function ShopArchive({ shop, onDone, onCancel }: { shop: ArchiveShop; onDone: () => void; onCancel: () => void }) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const sending = useRef(false);
  const [error, setError] = useState("");
  const title = shop.title || shop.name;
  const restore = !!shop.archived_at;
  const submit = async () => {
    if (sending.current || name !== title) return;
    sending.current = true; setBusy(true); setError("");
    try {
      await http.post(`/api/admin/shops/${shop.id}/${restore ? "restore" : "archive"}`, { confirm_name: name });
      onDone();
    } catch (e) { setError((e as Error).message); }
    finally { sending.current = false; setBusy(false); }
  };
  return <div className="acc-box" role="dialog" aria-label={restore ? "Восстановить магазин" : "Удалить магазин"}>
    <b>{restore ? "Восстановить" : "Удалить"} магазин «{title}»?</b>
    <div>Кабинет: {shop.workspace || "без кабинета"} · {shop.marketplace.toUpperCase()} · ID {shop.id}</div>
    <p>{restore
      ? `Магазин вернётся в рабочий список. ${shop.archived_was_active ? "Плановый сбор данных возобновится." : "Сбор останется выключенным, как до удаления."}`
      : "Магазин будет перенесён в архив: исчезнет из рабочих списков, новые плановые сборы отключатся. История и данные сохранятся. Уже начатый сбор может завершиться. Восстановить магазин можно в списке удалённых."}</p>
    <label>Для подтверждения введите название «{title}»: <input value={name} disabled={busy} onChange={e => setName(e.target.value)} /></label>
    {error && <div className="err">{error}</div>}
    <div className="acts"><button disabled={busy || name !== title} onClick={submit}>{busy ? "Сохраняю…" : restore ? "Восстановить магазин" : "Удалить в архив"}</button>
      <button disabled={busy} onClick={onCancel}>Отмена</button></div>
  </div>;
}
