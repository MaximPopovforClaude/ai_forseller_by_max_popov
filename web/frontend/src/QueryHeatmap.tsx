import { useEffect, useState } from 'react';
import { http } from './api';

type Result = { status: string; months: string[]; rows: {query:string;values:Record<string,number|null>}[]; updated_at?:string; completed?:number; queries:string[]; limit:number };
const messages:Record<string,string> = {empty:'Данные ещё не загружены.',queued:'Ожидает очереди Wildbox.',running:'Загружаем историю. Уже сохранённые месяцы доступны.',ready:'История сохранена.',no_key:'Подключите Wildbox в настройках аккаунта.',failed:'Загрузка остановлена из-за ошибки источника. Доступная история сохранена.',interrupted:'Загрузка прервалась. Доступная история сохранена.'};

export function QueryHeatmap({shop,nm}:{shop:number;nm:string}) {
  const ids=[...new Set(nm.split(',').map(s=>Number(s.trim())).filter(x=>x>0))];
  const selected=ids.length===1?ids[0]:null;
  const [data,setData]=useState<Result|null>(null),[error,setError]=useState(''),[rev,setRev]=useState(0),[busy,setBusy]=useState(false);
  const [q,setQ]=useState(''),[scale,setScale]=useState('row');
  useEffect(()=>{
    let live=true,timer:ReturnType<typeof setTimeout>;
    setData(null);setError('');setBusy(false);
    if(!selected)return;
    const read=()=>http.get<Result>(`/api/shops/${shop}/query_heatmap/${selected}`).then(r=>{
      if(!live)return;setData(r);
      if(['queued','running'].includes(r.status))timer=setTimeout(read,4000);
    }).catch(e=>{if(live)setError(e.message)});
    read();return()=>{live=false;clearTimeout(timer)};
  },[shop,selected,rev]);
  if(!selected)return <div className="hint">Выберите один товар в верхнем фильтре, чтобы увидеть его поисковые запросы по месяцам.</div>;
  const rows=data?.rows.filter(r=>r.query.toLowerCase().includes(q.toLowerCase()))||[];
  const max=Math.max(1,...(data?.rows||[]).flatMap(r=>Object.values(r.values).map(v=>v??0)));
  return <div className="query-heatmap">
    <div className="board-bar"><b>Частотность запросов по месяцам · Wildbox</b>
      <button disabled={busy||!data||['queued','running'].includes(data.status)} onClick={()=>{
        setBusy(true);setError('');http.post(`/api/shops/${shop}/query_heatmap/${selected}`).then(()=>setRev(x=>x+1)).catch(e=>setError(e.message)).finally(()=>setBusy(false));
      }}>{busy?'Запускаю…':'Загрузить / обновить из Wildbox'}</button>
      <input placeholder="Найти запрос" value={q} onChange={e=>setQ(e.target.value)}/>
      <select aria-label="Шкала тепловой карты" value={scale} onChange={e=>setScale(e.target.value)}><option value="row">Цвет: внутри запроса</option><option value="all">Цвет: общая шкала</option></select>
    </div>
    {error&&<div className="err">{error}</div>}
    <div className="hint">{data?messages[data.status]||data.status:'Читаем сохранённую историю…'} {data?.status==='running'&&`${data.completed||0} / ${data.queries.length} запросов.`}
      {data?.updated_at&&` Обновлено ${new Date(data.updated_at).toLocaleString('ru-RU')}.`}</div>
    <div className="hint">До {data?.limit||100} запросов товара из ответа Wildbox за 14 дней. Частотность относится ко всему запросу на WB, а не к показам вашего товара.
      Чем насыщеннее цвет, тем выше частотность. Прочерк — данных нет; 0 — подтверждённый ноль. Текущий месяц может быть неполным. Прогнозные месяцы исключены.</div>
    {!!data?.months.length&&<div className="board-wrap"><table className="board-t"><thead><tr><th>Запрос</th>{data.months.map(m=><th key={m}>{m.slice(5,7)}.{m.slice(0,4)}</th>)}</tr></thead>
      <tbody>{rows.map(r=>{const rowMax=Math.max(1,...Object.values(r.values).map(v=>v??0));return <tr key={r.query}><th>{r.query}</th>{data.months.map(m=>{
        const value=r.values[m],intensity=value==null?0:Math.log1p(value)/Math.log1p(scale==='row'?rowMax:max);
        return <td key={m} className="n" style={value!=null&&value>0?{backgroundColor:`rgba(122,84,224,${.12+.68*intensity})`}:undefined} title={`${r.query} · ${m.slice(0,7)}`}>{value==null?'—':new Intl.NumberFormat('ru-RU',{maximumFractionDigits:0}).format(value)}</td>;
      })}</tr>})}</tbody></table></div>}
    {data?.status==='ready'&&!data.rows.length&&<p className="hint">Wildbox не вернул запросов для этого товара.</p>}
  </div>;
}
