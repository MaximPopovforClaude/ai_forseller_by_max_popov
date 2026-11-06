import { useState } from "react";
import type { Tab } from "./api";

/** Настройка горизонтальной панели вкладок: какие показывать и в каком порядке . Остальные — в «Ещё» и боковом меню. */
export function TabBarEdit({ all, keys, onSave, onClose }: { all: Tab[]; keys: string[]; onSave: (keys: string[]) => void; onClose: () => void }) {
  const [list, setList] = useState<string[]>(keys.filter((k) => all.some((t) => t.key === k)));
  const [q, setQ] = useState("");
  const [drag, setDrag] = useState<number | null>(null);
  const title = (k: string) => all.find((t) => t.key === k)?.title || k;
  const move = (i: number, j: number) => setList((l) => {
    if (j < 0 || j >= l.length) return l;
    const n = [...l]; const [x] = n.splice(i, 1); n.splice(j, 0, x); return n;
  });
  const groups = [...new Set(all.map((t) => t.group))];
  const ql = q.trim().toLowerCase();
  return (
    <div className="modal-shade" onClick={onClose}>
      <div className="modal tbe" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h"><b>Вкладки на панели</b><span className="hint">— только эти и в этом порядке; остальные — в «Ещё ▾» и в боковом меню</span></div>
        <div className="tbe-cols">
          <div className="tbe-col">
            <b>На панели ({list.length})</b>
            {!list.length && <div className="hint">Пусто — на панели все вкладки, как раньше. Добавьте нужные справа.</div>}
            <ol className="tbe-list">{list.map((k, i) => (
              <li key={k} draggable onDragStart={() => setDrag(i)} onDragOver={(e) => e.preventDefault()}
                onDrop={() => { if (drag != null) move(drag, i); setDrag(null); }} className={drag === i ? "drag" : ""}>
                <span className="tbe-grip" title="Перетащите">⋮⋮</span><span className="tbe-t">{title(k)}</span>
                <button title="Выше" disabled={i === 0} onClick={() => move(i, i - 1)}>↑</button>
                <button title="Ниже" disabled={i === list.length - 1} onClick={() => move(i, i + 1)}>↓</button>
                <button title="Убрать с панели" onClick={() => setList((l) => l.filter((x) => x !== k))}>✕</button>
              </li>))}</ol>
          </div>
          <div className="tbe-col">
            <input placeholder="Найти вкладку…" value={q} onChange={(e) => setQ(e.target.value)} />
            <div className="tbe-all">{groups.map((g) => {
              const ts = all.filter((t) => t.group === g && (!ql || t.title.toLowerCase().includes(ql)));
              return ts.length ? <div key={g}><div className="tbe-g">{g}</div>
                {ts.map((t) => <label key={t.key}><input type="checkbox" checked={list.includes(t.key)}
                  onChange={(e) => setList((l) => e.target.checked ? [...l, t.key] : l.filter((x) => x !== t.key))} /> {t.title}</label>)}</div> : null;
            })}</div>
          </div>
        </div>
        <div className="full-btns">
          <button className="pri" onClick={() => onSave(list)}>Сохранить</button>
          <button onClick={() => onSave([])} title="На панели снова все вкладки по группам">Сбросить — все вкладки</button>
          <button onClick={onClose}>Отмена</button>
        </div>
      </div>
    </div>
  );
}
