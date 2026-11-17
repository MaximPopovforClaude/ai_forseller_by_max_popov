import { useEffect, useRef, useState } from 'react';

type Kind = 'stock' | 'assets' | 'settlement';
type Row = Record<string, string | null>;
type Payload = { rows: Row[]; includes_fbs?: boolean; exclusive?: boolean };
type Company = { id: number; title: string; shops: number[] };
type Shop = { id: number; title: string; name: string; marketplace: string };
type Batch = { id: number; kind: Kind; label: string; day: string; shop_id: number | null; payload: Payload; created_at: string };
type Meta = { shops: Shop[]; companies: Company[]; can_edit: boolean; common_access: boolean; today: string; categories: Record<string,string> };
type Value = { known: number; total: number|null; missing: number };
type Group = { kind: string; title: string; at: string|null; complete: boolean; old?: boolean; gaps?: string[]; values: Record<string,Value> };
type StockRow = { kind:string; nm_id:number|null; code:string|null; name:string|null; quantity:number|null; gaps?:Record<string,string>; [key:string]:unknown };
type Inventory = { groups: Group[]; note: string; stale?: boolean; rows?: StockRow[] };
type Gap = {message:string;shop_id?:number;kind?:string;metric?:string};
type GapView = {title:string;value:number;shop?:number;kinds?:string[];metric?:string;messages?:Gap[];signature?:string};
type Summary = { inventory_cost: number; seller_stock_cost: number; other_assets: number; receivables: number;
  liabilities: number; assets: number; net: number; gaps: string[]; partial_companies: string[]; fbs_replaced: number[];
  stock_totals: Record<number,Record<string,Value>>; gap_details?:Record<string,Gap[]> };
type Report = { shops: Record<number,Inventory>; errors: Record<number,string>;
  companies: { company: Company; batches: Batch[] }[]; variants: {with_fbs: Summary; without_fbs: Summary} };
const fmt = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
const money = (v: unknown) => v == null || !Number.isFinite(Number(v)) ? '—' : fmt.format(Number(v));
const when = (d: string|null) => d ? new Date(d.length === 10 ? d+'T12:00:00+03:00' : d).toLocaleString('ru-RU',
  { timeZone: 'Europe/Moscow', year: 'numeric', month: '2-digit', day: '2-digit', ...(d.length>10 ? {hour:'2-digit',minute:'2-digit'} as const : {}) }) : 'Нет снимка';
const title: Record<Kind,string> = {stock:'Собственный склад',assets:'Активы и обязательства',settlement:'Расчёты с площадкой'};
const metrics:Record<string,string>={quantity:'Количество',cost:'Себестоимость',seller:'Цена продавца',buyer:'После СПП / соинвеста'};
const stockSignature=(groups:Group[])=>JSON.stringify(groups.map(({kind,at,complete,old,values})=>({kind,at,complete,old,values})));
const fields: Record<Kind,[string,string][]> = {
  stock: [['code','Код товара'],['name','Название'],['quantity','Количество'],['cost','Себестоимость единицы']],
  assets: [['code','Код записи'],['name','Название'],['category','Категория'],['amount','Сумма, ₽'],['due','Срок погашения'],['note','Примечание']],
  settlement: [['before_spp','Продано до СПП, ₽'],['after_spp','Продано после СПП, ₽'],['unaccrued_net','До начисления: к получению, ₽'],['accrued','Начислено, не выплачено, ₽'],['note','Источник сверки']],
};
async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const r = await fetch(url, {credentials:'same-origin',...options});
  const body = await r.json().catch(() => null);
  if (!r.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : `Не удалось выполнить запрос (${r.status})`);
  return body;
}
const post = (body: unknown): RequestInit => ({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});

export function Balance({wsId}:{wsId:number}) {
  const base = `/api/workspaces/${wsId}/balance`;
  const [meta,setMeta] = useState<Meta|null>(null), [selected,setSelected] = useState<number[]>([]);
  const [day,setDay] = useState(''), [companyId,setCompanyId] = useState(0), [exclude,setExclude] = useState(true);
  const [result,setResult] = useState<Report|null>(null), [error,setError] = useState(''), [loading,setLoading] = useState(false);
  const [tick,setTick] = useState(0), [newCompany,setNewCompany] = useState(false);
  const [editor,setEditor] = useState<{company:Company;kind:Kind;batch?:Batch}|null>(null);
  const [history,setHistory] = useState<Company|null>(null);
  const [gapView,setGapView] = useState<GapView|null>(null);
  const query = [...selected].sort((a,b)=>a-b).join(',');
  useEffect(() => {
    const abort = new AbortController();setMeta(null);setResult(null);setError('');setSelected([]);setEditor(null);setHistory(null);setCompanyId(0);
    request<Meta>(base,{signal:abort.signal}).then(x=>{if(abort.signal.aborted)return;setMeta(x);setDay(x.today);}).catch(e=>{if(!abort.signal.aborted)setError(String(e.message));});
    return ()=>abort.abort();
  },[base]);
  useEffect(() => {
    const abort = new AbortController();setResult(null);setError('');setEditor(null);setHistory(null);setGapView(null);
    if(!query || !day) {setLoading(false);return;}
    setLoading(true);
    request<Report>(`${base}/report?day=${day}&shops=${query}`,{signal:abort.signal})
      .then(x=>{if(!abort.signal.aborted)setResult(x);}).catch(e=>{if(!abort.signal.aborted)setError(e.message);})
      .finally(()=>{if(!abort.signal.aborted)setLoading(false);});
    return ()=>abort.abort();
  },[base,query,day,tick]);
  const reload = () => setTick(t=>t+1);
  const choose = (id:number) => {setCompanyId(id);setSelected(meta?.companies.find(c=>c.id===id)?.shops || []);};
  const summary = result?.variants[exclude?'without_fbs':'with_fbs'];
  const shopName = (id:number) => {const s=meta?.shops.find(x=>x.id===id);return s ? `${s.marketplace.toUpperCase()} · ${s.title || s.name}` : String(id);};
  const activeKinds = (id:number) => result?.shops[id]?.groups.filter(g=>g.kind!=='fbs'||!(exclude||summary?.fbs_replaced.includes(id))).map(g=>g.kind)||[];
  const showStockGap = (id:number,k:string,v:Value,kinds:string[]) => setGapView({title:`${shopName(id)} · ${metrics[k]}`,
    value:v.total??v.known,shop:id,kinds,metric:k,signature:stockSignature(result?.shops[id]?.groups.filter(g=>kinds.includes(g.kind))||[])});
  return <section className="balance-page">
    <h2>Баланс</h2>
    <p className="hint">Состояние по последним сохранённым данным до выбранной даты. Все товары, включая исключённые из анализа. Суммы в рублях.</p>
    {error && <div className="err" role="alert">{error} <button onClick={reload}>Повторить</button></div>}
    {!meta && !error && <p role="status">Загружаю компании…</p>}
    {meta && <>
      <div className="balance-toolbar">
        <label>Компания <select aria-label="Компания" value={companyId} onChange={e=>choose(Number(e.target.value))}>
          <option value={0}>Выбрать магазины</option>{meta.companies.map(c=><option key={c.id} value={c.id}>{c.title}</option>)}
        </select></label>
        <label>На дату <input aria-label="Дата баланса" type="date" min="2024-01-01" max={meta.today} value={day} onChange={e=>setDay(e.target.value)} /></label>
        <label><input type="checkbox" checked={exclude} onChange={e=>{setExclude(e.target.checked);setGapView(null);}} /> Не учитывать FBS в балансе</label>
        <button onClick={reload} disabled={loading}>Обновить сохранённые данные</button>
        {meta.can_edit && <button onClick={()=>setNewCompany(!newCompany)}>Настроить компанию</button>}
      </div>
      <div className="balance-shops" role="group" aria-label="Магазины баланса">{meta.shops.map(s=><label key={s.id}>
        <input type="checkbox" checked={selected.includes(s.id)} onChange={e=>{setCompanyId(0);setSelected(ids=>e.target.checked?[...ids,s.id]:ids.filter(x=>x!==s.id));}} />{shopName(s.id)}
      </label>)}</div>
      {!meta.common_access && <p className="hint">Доступны остатки ваших магазинов. Общие активы и долги компании требуют полного доступа к кабинету.</p>}
      {newCompany && <CompanyForm base={base} meta={meta} onSaved={async()=>{const m=await request<Meta>(base);setMeta(m);setNewCompany(false);reload();}} />}
      {!query && <p>Выбери компанию или отметь магазины. Общие активы компании учитываются один раз при выборе всех её магазинов.</p>}
      {loading && <p role="status">Подготавливаю баланс выбранных магазинов…</p>}
      {summary && <>
        <div className="balance-cards">{[
          ['Учтено активов','assets'],['Обязательства','liabilities'],['Активы минус обязательства','net'],
          ['Товары МП по себестоимости','inventory_cost'],['Собственный склад','seller_stock_cost'],['К получению от площадок','receivables'],
        ].map(([label,k])=><div className="balance-card" key={k}><span>{label}</span><strong>{money(summary[k as keyof Summary])} ₽</strong>
          {!!summary.gap_details?.[k]?.length&&<button className="balance-gap-link" onClick={()=>setGapView({title:label,value:Number(summary[k as keyof Summary]),messages:summary.gap_details?.[k]})}>Неполные данные · подробнее</button>}
        </div>)}</div>
        {!!summary.gaps.length && <details className="balance-gaps"><summary>Баланс неполный: {summary.gaps.length} предупреждений</summary>
          <ul>{summary.gaps.map((s,i)=><li key={i}>{s}</li>)}</ul><p>Карточки показывают учтённую часть. Неизвестные суммы не заменены нулями.</p></details>}
        {!!summary.partial_companies.length && <p className="disclaimer">Выбрана часть магазинов: {summary.partial_companies.join(', ')}. Общий склад, активы и долги этих компаний в сумму не включены. Выбери все магазины компании для полного состава.</p>}
        {!!summary.fbs_replaced.length && <p className="hint">FBS не прибавлен повторно: в собственном складе подтверждён полный физический запас FBS компании.</p>}
        <h3>Запасы маркетплейсов</h3>
        <p className="hint">Три оценки показаны рядом. В активы входит только себестоимость. При пробелах крупно показана учтённая часть; нажми на пометку под числом, чтобы увидеть причины.</p>
        {selected.map(id=><div className="balance-panel" key={id}>
          <h4>{shopName(id)}</h4>{result?.errors[id] && <p className="err">{result.errors[id]}</p>}
          {result?.shops[id] && <>
            <div className="balance-scroll"><table><thead><tr><th>Запас</th><th>Шт.</th><th>Себестоимость, ₽</th><th>Цена продавца, ₽</th><th>После СПП / соинвеста, ₽</th><th>Снимок, МСК</th></tr></thead>
              <tbody>{result.shops[id].groups.map(g=><tr key={g.kind} className={g.kind==='fbs'&&(exclude||summary.fbs_replaced.includes(id))?'balance-excluded':''}>
                <th>{g.title}{g.kind==='fbs'&&(exclude||summary.fbs_replaced.includes(id))?' · не в итоге':''}</th>
                {['quantity','cost','seller','buyer'].map(k=><td key={k}><BalanceValue value={g.values[k]} partial={!g.complete||g.old||result.shops[id].stale}
                  label={`${g.title} · ${metrics[k]}`} onDetails={()=>showStockGap(id,k,g.values[k],[g.kind])}/></td>)}
                <td>{when(g.at)}{!g.complete && <small>Полнота не подтверждена</small>}</td>
              </tr>)}{summary.stock_totals?.[id] && <tr className="balance-total"><th>Итого с учётом выбора FBS, включая пути</th>
                {['quantity','cost','seller','buyer'].map(k=><td key={k}><BalanceValue value={summary.stock_totals[id][k]}
                  partial={result.shops[id].stale||result.shops[id].groups.some(g=>activeKinds(id).includes(g.kind)&&g.old)} label={`Итого · ${metrics[k]}`}
                  onDetails={()=>showStockGap(id,k,summary.stock_totals[id][k],activeKinds(id))}/></td>)}<td>По источникам выше</td>
              </tr>}</tbody></table></div>
            <p className="hint">{result.shops[id].note}</p><StockDetails base={base} shop={id} day={day} />
          </>}
        </div>)}
        <h3>Компании: расчёты, склад, активы и долги</h3>
        {!result?.companies.length && <p>Привяжи магазины к компании, чтобы добавить общий склад и финансовые остатки.</p>}
        {result?.companies.map(({company:c,batches})=><div className="balance-panel" key={c.id}>
          <div className="balance-toolbar"><h4>{c.title}</h4><button onClick={()=>setHistory(c)}>История записей</button>
            {meta.can_edit && (['settlement','stock','assets'] as Kind[]).map(k=><button key={k} onClick={()=>setEditor({company:c,kind:k,
              batch:k==='assets'?batches.find(b=>b.kind===k):undefined})}>{k==='assets'?'Открыть реестр':'+ '+title[k]}</button>)}
          </div>
          <p className="hint">{c.shops.map(shopName).join(' · ')}</p>
          {batches.map(b=><details key={b.id}><summary>{title[b.kind]} · {b.label}{b.shop_id?' · '+shopName(b.shop_id):''} · {when(b.day)} · {b.payload.rows.length} строк</summary>
            {b.kind==='settlement' && <p className="hint">Сверка внесена вручную / из Excel. До и после начисления — разные суммы. Цена продажи не равна сумме к получению.</p>}
            <RegisterTable kind={b.kind} rows={b.payload.rows} categories={meta.categories} />
            {meta.can_edit && <button onClick={()=>setEditor({company:c,kind:b.kind,batch:b})}>Изменить снимок с сохранением истории</button>}
          </details>)}
          {!batches.length && <p>Нет введённых остатков. Отсутствие записи не означает ноль.</p>}
        </div>)}
      </>}
      {history && <History base={base} company={history} categories={meta.categories} onClose={()=>setHistory(null)} />}
      {gapView && <GapDetails key={`${base}:${day}:${gapView.shop}:${gapView.metric}:${gapView.kinds?.join(',')}:${gapView.title}`} base={base} day={day} view={gapView}
        onClose={()=>setGapView(null)} onShop={gap=>{
          const id=gap.shop_id!;const kinds=gap.kind?[gap.kind]:activeKinds(id);
          const groups=result?.shops[id]?.groups.filter(g=>kinds.includes(g.kind))||[];
          showStockGap(id,gap.metric||'cost',{known:groups.reduce((sum,g)=>sum+g.values[gap.metric||'cost'].known,0),total:null,missing:0},kinds);
        }} />}
      {editor && <Editor key={`${wsId}:${editor.company.id}:${editor.kind}:${editor.batch?.id||0}:${day}`} base={base} meta={meta} day={day} {...editor}
        onClose={()=>setEditor(null)} onSaved={()=>{setEditor(null);reload();}} />}
      <p className="hint">МойСклад, 1С и банки будут подключены отдельными этапами. До этого деньги и остальные активы доступны в ручном реестре.</p>
    </>}
  </section>;
}

function BalanceValue({value,partial,label,onDetails}:{value:Value;partial?:boolean;label:string;onDetails:()=>void}) {
  const incomplete=partial||value.total==null||value.missing>0;
  return <><strong className="balance-value" title={incomplete?'Учтённая часть по доступным данным':undefined}>{money(value.total??value.known)}</strong>
    {incomplete&&<button className="balance-gap-link" aria-label={`Пробелы: ${label}`} onClick={onDetails}>
      Учтено частично{value.missing>0?` · пробелов: ${value.missing}`:''}</button>}</>;
}

function GapDetails({base,day,view,onClose,onShop}:{base:string;day:string;view:GapView;onClose:()=>void;onShop:(gap:Gap)=>void}) {
  const [data,setData]=useState<Inventory|null>(null),[error,setError]=useState(''),[page,setPage]=useState(0),[retry,setRetry]=useState(0);
  const close=useRef<HTMLButtonElement>(null);
  useEffect(()=>{
    const before=document.activeElement as HTMLElement|null;close.current?.focus();
    return ()=>before?.focus?.();
  },[]);
  useEffect(()=>{
    const a=new AbortController();setData(null);setError('');setPage(0);
    if(view.shop!=null)request<Inventory>(`${base}/shops/${view.shop}?day=${day}`,{signal:a.signal})
      .then(d=>{if(!a.signal.aborted)setData(d);}).catch(e=>{if(!a.signal.aborted)setError(String(e.message));});
    return()=>a.abort();
  },[base,day,view.shop,retry]);
  const groups=data?.groups.filter(g=>view.kinds?.includes(g.kind))||[];
  const rows=data?.rows?.filter(r=>view.kinds?.includes(r.kind)&&r.gaps?.[view.metric||'cost'])||[];
  const latest=groups.reduce((sum,g)=>sum+g.values[view.metric||'cost'].known,0);
  const changed=!!data&&(Math.abs(latest-view.value)>.005||stockSignature(groups)!==view.signature);
  return <div className="balance-modal" role="dialog" aria-modal="true" aria-label="Расшифровка пробелов" onKeyDown={e=>{if(e.key==='Escape')onClose();}}>
    <div className="balance-editor balance-gap-detail"><button ref={close} onClick={onClose}>Закрыть</button><h3>{view.title}</h3>
      <strong className="balance-gap-amount">{money(view.value)}{view.metric==='quantity'?' шт.':' ₽'}</strong>
      <p className="hint">Учтённая часть по доступным данным. Пробелы не считаются нулём и не добавляются к сумме. Нулевая учтённая часть не подтверждает отсутствие запасов или обязательств.</p>
      {view.messages&&<ul>{view.messages.map((g,i)=><li key={i}><p>{g.message}</p>{g.shop_id!=null&&g.metric&&
        <button onClick={()=>onShop(g)}>Товары и причины · магазин {g.shop_id}</button>}</li>)}</ul>}
      {view.shop!=null&&!data&&!error&&<p role="status">Загружаю расшифровку…</p>}
      {error&&<p role="alert">{error} <button onClick={()=>setRetry(x=>x+1)}>Повторить чтение</button></p>}
      {data&&<>
        {changed&&<p role="status" className="balance-gaps">Сохранённые данные обновились после открытия баланса. В расшифровке учтено {money(latest)}; закрой окно и обнови баланс, чтобы сверить суммы.</p>}
        {data.stale&&<p>Показан предыдущий расчёт: свежий ещё готовится.</p>}
        {groups.map(g=><div key={g.kind}><h4>{g.title} · {when(g.at)}</h4>{(g.gaps||[]).map((s,i)=><p key={i}>{s}</p>)}</div>)}
        {!!rows.length&&<><p>Строк с пробелами в этом показателе: {rows.length}. Стоимость неучтённой части неизвестна.</p>
          <div className="balance-scroll"><table><thead><tr><th>Запас</th><th>Артикул продавца / МП</th><th>Товар</th><th>Количество</th><th>Что не учтено и почему</th></tr></thead>
          <tbody>{rows.slice(page*100,(page+1)*100).map((r,i)=><tr key={i}><td>{groups.find(g=>g.kind===r.kind)?.title||r.kind}</td>
            <td>{r.code||'Не указан'}<small>{r.nm_id??'Артикул МП не указан'}</small></td><td>{r.name||'Название не сохранено'}</td>
            <td>{money(r.quantity)}</td><td>{r.gaps?.[view.metric||'cost']}</td></tr>)}</tbody></table></div>
          {rows.length>100&&<p><button disabled={!page} onClick={()=>setPage(p=>p-1)}>Назад</button> {page*100+1}–{Math.min((page+1)*100,rows.length)} из {rows.length} <button disabled={(page+1)*100>=rows.length} onClick={()=>setPage(p=>p+1)}>Дальше</button></p>}
        </>}
        {!rows.length&&<p>{groups.some(g=>g.gaps?.length)?'Ограничение относится к источнику или дате снимка. Точный список недостающих товаров неизвестен.':'В доступных строках этого показателя пробелов нет. Сравни дату снимка и обнови баланс, если данные изменились.'}</p>}
      </>}
    </div>
  </div>;
}

function CompanyForm({base,meta,onSaved}:{base:string;meta:Meta;onSaved:()=>Promise<void>}) {
  const [name,setName]=useState(''),[ids,setIds]=useState<number[]>([]),[busy,setBusy]=useState(false),[err,setErr]=useState('');
  const taken=new Set(meta.companies.flatMap(c=>c.shops));
  return <form className="balance-panel" onSubmit={async e=>{e.preventDefault();setBusy(true);setErr('');try{await request(base+'/companies',post({title:name,shops:ids}));await onSaved();}catch(x){setErr(String(x));}finally{setBusy(false);}}}>
    <h3>Новая компания</h3><input aria-label="Название компании" placeholder="Название компании" value={name} maxLength={200} onChange={e=>setName(e.target.value)} required />
    <p className="hint">Привяжи все магазины одного юрлица. Магазин может относиться только к одной компании.</p>
    <div className="balance-shops">{meta.shops.filter(s=>!taken.has(s.id)).map(s=><label key={s.id}><input type="checkbox" checked={ids.includes(s.id)}
      onChange={e=>setIds(a=>e.target.checked?[...a,s.id]:a.filter(x=>x!==s.id))} />{s.marketplace.toUpperCase()} · {s.title||s.name}</label>)}</div>
    {err&&<p role="alert" className="err">{err}</p>}<button disabled={busy||!ids.length||!name.trim()}>Сохранить компанию</button>
  </form>;
}

function RegisterTable({kind,rows,categories,onEdit}:{kind:Kind;rows:Row[];categories:Record<string,string>;onEdit?:(index:number)=>void}) {
  const [page,setPage]=useState(0);useEffect(()=>setPage(0),[rows]);
  return <><div className="balance-scroll"><table><thead><tr>{fields[kind].map(([k,t])=><th key={k}>{t}</th>)}{onEdit&&<th>Правка</th>}</tr></thead><tbody>
    {rows.slice(page*100,(page+1)*100).map((r,i)=><tr key={i}>{fields[kind].map(([k,label])=><td key={k}>{k==='category'?categories[r[k]||'']||r[k]:r[k]??'—'}
      {kind==='settlement'&&k!=='note'&&r[k]==null&&<details><summary>Почему нет суммы</summary><p>Поле «{label}» не заполнено в этой сверке. Автоматическая сверка ещё не подключена. Внесите подтверждённую сумму вручную или загрузите Excel. Пропуск не означает ноль.</p></details>}
    </td>)}{onEdit&&<td><button onClick={()=>onEdit(page*100+i)}>Изменить строку</button></td>}</tr>)}
  </tbody></table></div>{rows.length>100&&<p><button disabled={!page} onClick={()=>setPage(x=>x-1)}>Назад</button> {page*100+1}–{Math.min((page+1)*100,rows.length)} из {rows.length} <button disabled={(page+1)*100>=rows.length} onClick={()=>setPage(x=>x+1)}>Дальше</button></p>}</>;
}

function Editor({base,meta,day,company,kind,batch,onClose,onSaved}:{base:string;meta:Meta;day:string;company:Company;kind:Kind;batch?:Batch;onClose:()=>void;onSaved:()=>void}) {
  const [rows,setRows]=useState<Row[]>(batch?.payload.rows || (kind==='settlement'?[{}]:[]));
  const [label,setLabel]=useState(batch?.label || (kind==='stock'?'Основной склад':title[kind]));
  const [shop,setShop]=useState(batch?.shop_id||company.shops[0]),[draft,setDraft]=useState<Row>({});
  const [includes,setIncludes]=useState(batch?.payload.includes_fbs||false),[confirmed,setConfirmed]=useState(false);
  const [preview,setPreview]=useState(false),[busy,setBusy]=useState(false),[err,setErr]=useState('');
  const [editing,setEditing]=useState<number|null>(null);
  const key=useRef(crypto.randomUUID()); const alive=useRef(true);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  const change=()=>{setPreview(false);setConfirmed(false);key.current=crypto.randomUUID();};
  async function load(file:File) {
    setBusy(true);setErr('');change();
    try{const p=await request<Payload>(`${base}/companies/${company.id}/preview/${kind}`,{method:'POST',headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},body:file});if(alive.current){setRows(p.rows);setDraft({});setEditing(null);setPreview(true);}}
    catch(e){if(alive.current)setErr(String(e));}finally{if(alive.current)setBusy(false);}
  }
  async function save() {
    setBusy(true);setErr('');try{await request(`${base}/companies/${company.id}/batches`,post({kind,label,day,shop_id:kind==='settlement'?shop:null,
      payload:{rows,includes_fbs:includes,exclusive:kind==='settlement'},request_key:key.current,previous_id:batch?.id||null}));if(alive.current)onSaved();}
    catch(e){if(alive.current)setErr(String(e));}finally{if(alive.current)setBusy(false);}
  }
  return <div className="balance-modal" role="dialog" aria-modal="true" aria-label={title[kind]}><div className="balance-editor">
    <div className="balance-toolbar"><h3>{company.title} · {title[kind]}</h3><button onClick={onClose} disabled={busy}>Закрыть</button></div>
    <p>Остаток на {when(day)}. Сохранение создаёт новую версию; предыдущая остаётся в истории.</p>
    {kind==='stock'&&<label>Физический склад <input value={label} maxLength={100} disabled={!!batch||busy} onChange={e=>{setLabel(e.target.value);change();}} /></label>}
    {kind==='settlement'&&<><label>Магазин <select value={shop} disabled={!!batch||busy} onChange={e=>{setShop(Number(e.target.value));setRows([{}]);change();}}>{company.shops.map(id=><option key={id} value={id}>{meta.shops.find(s=>s.id===id)?.title||id}</option>)}</select></label>
      <p className="hint">Полный остаток на дату, не сумма продаж за месяц. Введите две непересекающиеся стадии. К получению — после известных удержаний; пустое поле означает неизвестную сумму, 0 — подтверждённый ноль.</p></>}
    <div className="balance-toolbar"><a className="btn" href={`${base}/template/${kind}`}>Скачать Excel-шаблон</a>
      <label>Загрузить Excel <input aria-label="Файл баланса" type="file" accept=".xlsx" disabled={busy} onChange={e=>{const f=e.target.files?.[0];if(f)void load(f);e.target.value='';}} /></label></div>
    <p className="hint">Excel заменяет весь этот реестр / снимок склада. Для дополнения сначала открой действующий снимок. До подтверждения данные не сохраняются.</p>
    {kind==='stock'&&<label><input type="checkbox" checked={includes} disabled={busy} onChange={e=>{setIncludes(e.target.checked);change();}} /> Этот снимок включает весь физический запас FBS компании: FBS из магазинов не прибавлять</label>}
    <fieldset disabled={busy}><legend>{kind==='settlement'?'Суммы сверки':'Добавить строку вручную'}</legend><div className="balance-inputs">
      {fields[kind].map(([k,t])=><label key={k}>{t}{k==='category'?<select value={draft[k]||''} onChange={e=>setDraft(r=>({...r,[k]:e.target.value}))}>
        <option value="">Выберите</option>{Object.entries(meta.categories).map(([code,name])=><option key={code} value={code}>{name}</option>)}</select>:
        <input type={k==='due'?'date':'text'} value={(kind==='settlement'?rows[0]?.[k]:draft[k])||''} maxLength={500}
          onChange={e=>{if(kind==='settlement'){setRows(rs=>[{...rs[0],[k]:e.target.value}]);change();}else setDraft(r=>({...r,[k]:e.target.value}));}} />}</label>)}
    </div>{kind!=='settlement'&&<><button onClick={()=>{setRows(rs=>editing==null?[...rs,draft]:rs.map((r,i)=>i===editing?draft:r));setDraft({});setEditing(null);change();}}>{editing==null?'Добавить строку':'Применить правку к черновику'}</button>
      {editing!=null&&<button onClick={()=>{setRows(rs=>rs.filter((_,i)=>i!==editing));setDraft({});setEditing(null);change();}}>Убрать строку из черновика</button>}</>}</fieldset>
    {kind!=='settlement'&&<><RegisterTable kind={kind} rows={rows} categories={meta.categories} onEdit={busy?undefined:i=>{setEditing(i);setDraft({...rows[i]});change();}} /><div className="balance-toolbar">
      <button disabled={busy||!rows.length||editing!=null} onClick={()=>{setRows(rs=>rs.slice(0,-1));change();}}>Убрать последнюю строку из черновика</button>
      <button disabled={busy||!rows.length} onClick={()=>{setRows([]);setDraft({});setEditing(null);change();}}>Очистить черновик</button></div></>}
    {err&&<p className="err" role="alert">{err}</p>}
    {editing!=null&&<p className="hint">Сначала примени правку строки к черновику.</p>}
    {!preview&&<button disabled={busy||editing!=null} onClick={()=>{setPreview(true);setConfirmed(false);}}>Предпросмотр перед сохранением</button>}
    {preview&&<div className="balance-confirm"><strong>Предпросмотр: {rows.length} строк · {company.title} · {when(day)}</strong>
      {kind==='settlement'&&<RegisterTable kind={kind} rows={rows} categories={meta.categories} />}
      <p>{rows.length?'Будет сохранён полный новый снимок этого реестра.':'Будет записан подтверждённый пустой реестр (нулевой остаток).'}</p>
      <label><input type="checkbox" checked={confirmed} disabled={busy} onChange={e=>setConfirmed(e.target.checked)} />{kind==='settlement'?'Подтверждаю остатки на дату: суммы до начисления и начисленные не пересекаются':'Подтверждаю полный состав и отсутствие повторного учёта этих активов'}</label>
      <button disabled={!confirmed||busy} onClick={()=>void save()}>{busy?'Сохраняю…':'Подтвердить и сохранить'}</button>
    </div>}
  </div></div>;
}

function StockDetails({base,shop,day}:{base:string;shop:number;day:string}) {
  const [data,setData]=useState<Inventory|null>(null),[err,setErr]=useState(''),[open,setOpen]=useState(false),[page,setPage]=useState(0);
  useEffect(()=>{const a=new AbortController();setData(null);setErr('');setPage(0);if(open)request<Inventory>(`${base}/shops/${shop}?day=${day}`,{signal:a.signal}).then(d=>{if(!a.signal.aborted)setData(d);}).catch(e=>{if(!a.signal.aborted)setErr(String(e));});return()=>a.abort();},[base,shop,day,open]);
  return <><button onClick={()=>setOpen(x=>!x)}>{open?'Скрыть товары':'Показать товары'}</button>{open&&<>
    {err&&<p role="alert">{err}</p>}{!data&&!err&&<p role="status">Загружаю товары…</p>}
    {data&&<div className="balance-scroll"><table><thead><tr>{['Запас','Артикул МП','Код продавца','Название','Количество','Себестоимость / шт.','Цена продавца / шт.','Цена покупателя / шт.'].map(t=><th key={t}>{t}</th>)}</tr></thead>
      <tbody>{data.rows?.slice(page*100,(page+1)*100).map((r,i)=><tr key={i}>{['kind','nm_id','code','name','quantity','cost','seller','buyer'].map(k=><td key={k}>{r[k]==null?'—':String(r[k])}</td>)}</tr>)}</tbody></table>
      <button disabled={!page} onClick={()=>setPage(x=>x-1)}>Назад</button> {page+1} <button disabled={(page+1)*100>=(data.rows?.length||0)} onClick={()=>setPage(x=>x+1)}>Дальше</button></div>}
  </>}</>;
}

function History({base,company,categories,onClose}:{base:string;company:Company;categories:Record<string,string>;onClose:()=>void}) {
  const [items,setItems]=useState<Batch[]>([]),[detail,setDetail]=useState<Batch|null>(null),[err,setErr]=useState('');
  const seq=useRef(0);useEffect(()=>{const a=new AbortController();request<{rows:Batch[]}>(`${base}/companies/${company.id}/history`,{signal:a.signal}).then(r=>{if(!a.signal.aborted)setItems(r.rows);}).catch(e=>{if(!a.signal.aborted)setErr(String(e));});return()=>{a.abort();seq.current++;};},[base,company.id]);
  return <div className="balance-modal" role="dialog" aria-modal="true" aria-label="История баланса"><div className="balance-editor"><button onClick={onClose}>Закрыть</button><h3>{company.title} · последние 200 версий</h3>
    {err&&<p role="alert">{err}</p>}{items.map(b=><p key={b.id}><button onClick={async()=>{const n=++seq.current;setDetail(null);try{const d=await request<Batch>(`${base}/companies/${company.id}/batches/${b.id}`);if(seq.current===n)setDetail(d);}catch(e){if(seq.current===n)setErr(String(e));}}}>{when(b.day)} · {title[b.kind]} · {b.label} · записано {when(b.created_at)}</button></p>)}
    {detail&&<RegisterTable kind={detail.kind} rows={detail.payload.rows} categories={categories} />}
  </div></div>;
}
