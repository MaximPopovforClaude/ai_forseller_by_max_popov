import { useEffect, useRef, useState } from "react";
import { http } from "./api";
import type { TabData } from "./api";

type Row = [string, string, string]; // группа, показатель, период
type Hid = [string, string, string, number?]; // + место, где колонка стояла
type Preset = {name:string;cols:Row[];hidden:Hid[]};
type Presets = {items:Preset[];revision:string|null};

/** Настройка колонок сводной: как в таблице «Выберите показатель и период» — показатель листа БД и период для каждой колонки. */
export function LayoutEditor({ data, shop, presetsEnabled = true, onSave }: { data: TabData; shop:number; presetsEnabled?:boolean; onSave: (v: { cols: Row[]; hidden: Hid[] } | null) => Promise<unknown> }) {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<Row[]>(data.col_layout || []);
  const [busy, setBusy] = useState(false);
  const [hidden, setHidden] = useState<Hid[]>(data.col_hidden || []);
  const [showHid, setShowHid] = useState(false);
  const [allPeriod,setAllPeriod]=useState('текущая неделя'),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const [presets,setPresets]=useState<Presets|null>(null),[presetName,setPresetName]=useState(''),[chosen,setChosen]=useState('');
  const [loading,setLoading]=useState(false),[refresh,setRefresh]=useState(0);
  const alive=useRef(true);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  useEffect(()=>{
    let cancelled=false;
    if(!open||!presetsEnabled)return;
    setLoading(true);setPresets(null);
    http.get<Presets>(`/api/shops/${shop}/prefs/svodwb_presets`).then(v=>{if(!cancelled)setPresets(v);})
      .catch(e=>{if(!cancelled)setError(String(e.message));}).finally(()=>{if(!cancelled)setLoading(false);});
    return()=>{cancelled=true;};
  },[open,shop,refresh,presetsEnabled]);
  useEffect(() => { setRows(data.col_layout || []); setHidden(data.col_hidden || []); }, [data.col_layout, data.col_hidden]);
  const hide = (i: number) => { setHidden((h) => [...h, [...rows[i], i] as Hid]); setRows(rows.filter((_, k) => k !== i)); };
  const restore = (j: number) => {
    const [g, m, p, at] = hidden[j];
    setRows((r) => { const a = [...r]; a.splice(Math.min(at ?? a.length, a.length), 0, [g, m, p]); return a; });
    setHidden((h) => h.filter((_, k) => k !== j));
  };
  const metrics = data.metrics || [];
  const periods = data.periods || [];
  const set = (i: number, j: number, v: string) => setRows((r) => r.map((x, k) => (k === i ? (x.map((y, m) => (m === j ? v : y)) as Row) : x)));
  const move = (i: number, d: number) => setRows((r) => {
    const a = [...r]; const j = i + d; if (j < 0 || j >= a.length) return a; [a[i], a[j]] = [a[j], a[i]]; return a;
  });
  const save = async (v: { cols: Row[]; hidden: Hid[] } | null) => {
    setBusy(true);setError('');setNotice('');
    try {await onSave(v);if(alive.current)setOpen(false);}
    catch(e){if(alive.current)setError(e instanceof Error?e.message:String(e));}
    finally{if(alive.current)setBusy(false);}
  };
  const writePresets=async(items:Preset[])=>{
    if(!presets)return;
    setBusy(true);setError('');setNotice('');
    try {
      const saved=await http.put<Presets>(`/api/shops/${shop}/prefs/svodwb_presets`,{value:{items},revision:presets.revision});
      if(alive.current){setPresets(saved);setNotice('Пресеты сохранены в твоём аккаунте для этого магазина.');}
    }catch(e){if(alive.current)setError(e instanceof Error?e.message:String(e));}
    finally{if(alive.current)setBusy(false);}
  };
  const named=presets?.items.find(p=>p.name.toLocaleLowerCase()===presetName.trim().toLocaleLowerCase());
  const applyPeriod=()=>{
    setRows(r=>r.map(([g,m,p])=>[g,m,m==='разница'?p:allPeriod]));
    setHidden(h=>h.map(([g,m,p,at])=>[g,m,m==='разница'?p:allPeriod,...(at==null?[]:[at])] as Hid));
    setNotice('Период выбран для всех показателей, включая скрытые. Нажми «Сохранить», чтобы обновить таблицу.');
  };

  return (
    <div className="chart">
      <div className="chart-bar">
        <button disabled={busy} onClick={() => setOpen(!open)}>{open ? "▾" : "▸"} Колонки и периоды ({rows.length})</button>
        {open && <>
          <button disabled={busy} onClick={() => save({ cols: rows, hidden })}>Сохранить</button>
          <button disabled={busy} onClick={() => save(null)} title="Стандартная раскладка">Сбросить к стандартным</button>
          <button disabled={busy} onClick={() => setRows([...rows, ["", metrics[0] || "", periods[0] || "вчера"]])}>+ колонка</button>
        </>}
      </div>
      {error&&<div role="alert" className="err">{error}</div>}
      {notice&&<div role="status" className="hint">{notice}</div>}
      {open && (
        <fieldset disabled={busy} className="layout-list layout-settings">
          <div className="chart-bar"><label>Период для всех колонок <select aria-label="Период для всех колонок" value={allPeriod} onChange={e=>setAllPeriod(e.target.value)}>
            {periods.map(p=><option key={p}>{p}</option>)}
          </select></label><button onClick={applyPeriod}>Выбрать для всех</button></div>
          {presetsEnabled&&<div className="layout-presets">
            <b>Мои пресеты</b>{loading&&<span role="status">Загружаю…</span>}
            <div className="chart-bar"><select aria-label="Пресет периодов" value={chosen} disabled={!presets} onChange={e=>{setChosen(e.target.value);setPresetName(e.target.value);}}>
              <option value="">Выбрать пресет</option>{presets?.items.map(p=><option key={p.name}>{p.name}</option>)}
            </select><button disabled={!presets?.items.some(p=>p.name===chosen)} onClick={()=>{
              const p=presets?.items.find(p=>p.name===chosen);if(p){setRows(p.cols);setHidden(p.hidden);void save({cols:p.cols,hidden:p.hidden});}
            }}>Применить пресет</button><button disabled={!presets?.items.some(p=>p.name===chosen)} onClick={()=>void writePresets(presets!.items.filter(p=>p.name!==chosen))}>Удалить пресет</button>
            <button onClick={()=>{setError('');setRefresh(x=>x+1);}}>Перечитать пресеты</button></div>
            <div className="chart-bar"><input aria-label="Название пресета" maxLength={80} placeholder="Например: Всё за текущую неделю" value={presetName} onChange={e=>setPresetName(e.target.value)}/>
              <button disabled={!presets||!presetName.trim()||!rows.length} onClick={()=>{
                const name=presetName.trim();void writePresets([...(presets?.items||[]).filter(p=>p!==named),{name,cols:rows,hidden}]);
              }}>{named?'Обновить пресет':'Сохранить пресет'}</button></div>
            <div className="hint">Сохраняются показатели, их периоды, порядок и скрытые колонки. «Текущая неделя» в пресете будет переходить на новую неделю автоматически.</div>
          </div>}
          {rows.map((r, i) => (
            <div key={i} className="layout-row">
              <input className="grp-in" placeholder="группа" value={r[0]} onChange={(e) => set(i, 0, e.target.value)} />
              <select value={r[1]} onChange={(e) => set(i, 1, e.target.value)}>
                {metrics.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
              {r[1] !== "разница" ? (
                <select value={r[2]} onChange={(e) => set(i, 2, e.target.value)}>
                  {periods.map((p) => <option key={p} value={p}>{p}</option>)}
                </select>
              ) : <span className="hint">две предыдущие колонки</span>}
              <button onClick={() => move(i, -1)}>↑</button>
              <button onClick={() => move(i, 1)}>↓</button>
              <button title="Скрыть колонку (вернуть можно из «Скрытых»)" onClick={() => hide(i)}>✕</button>
            </div>
          ))}
          <button className="hid-h" onClick={() => setShowHid(!showHid)}>{showHid ? "▾" : "▸"} Скрытые ({hidden.length})</button>
          {showHid && (hidden.length ? hidden.map((h, j) => (
            <div key={j} className="layout-row hid-row">
              <span className="hid-t">{h[0] && <b>{h[0]} · </b>}{h[1]}{h[1] !== "разница" && h[2] ? ` · ${h[2]}` : ""}</span>
              <button title="Вернуть на прежнее место" onClick={() => restore(j)}>↩ вернуть</button>
            </div>
          )) : <div className="hint">Скрытых колонок нет. Нажмите ✕ у колонки — она попадёт сюда.</div>)}
          {(hidden.length > 0 || rows.length !== (data.col_layout || []).length) && <div className="hint">Изменения применятся после «Сохранить».</div>}
          <div className="hint">Правки колонок и общего периода применяются к таблице после «Сохранить».</div>
        </fieldset>
      )}
    </div>
  );
}
