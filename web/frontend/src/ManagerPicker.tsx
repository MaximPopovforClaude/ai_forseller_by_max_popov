export function ManagerPicker({ value, items, onChange }: {
  value: string; items: { id: number; name: string }[]; onChange: (value: string) => void;
}) {
  const selected = new Set(value.split(",").filter(Boolean).map(Number));
  const title = selected.size === 0 ? "Все менеджеры" : selected.size === 1
    ? items.find(x => selected.has(x.id))?.name || "Выбран менеджер" : `Менеджеры: ${selected.size}`;
  return <details className="manager-picker"><summary title="Показатели по артикулам выбранных менеджеров">👤 {title}</summary>
    <div className="manager-picker-list">
      <button type="button" onClick={() => onChange("")}>Все менеджеры</button>
      {items.map(x => <label key={x.id}><input type="checkbox" checked={selected.has(x.id)} onChange={e => {
        const next = new Set(selected);
        if (e.target.checked) next.add(x.id); else next.delete(x.id);
        onChange([...next].sort((a, b) => a - b).join(","));
      }} /> {x.name}</label>)}
      <small className="hint">Без отметок — все менеджеры, включая товары без назначения.</small>
    </div>
  </details>;
}
