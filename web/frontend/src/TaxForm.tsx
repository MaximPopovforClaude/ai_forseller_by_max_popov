import { useEffect, useState } from "react";
import { api, type TabData } from "./api";

/** Настройки магазина: система налогообложения (как лист «СНО»). Ставки вводятся в процентах. */
export function TaxForm({ shop, data, onSaved }: { shop: number; data: TabData; onSaved: () => void }) {
  const cur = data.current || {};
  const [regime, setRegime] = useState(String(cur.regime || "Другая СНО"));
  const [rate, setRate] = useState(String(Number(cur.rate || 0) * 100));
  const [vat, setVat] = useState(String(Number(cur.vat_rate || 0) * 100));
  const [vatWb, setVatWb] = useState(String(Number(cur.vat_deduct_wb || 0) * 100));
  const [costVat, setCostVat] = useState(!!cur.cost_vat);
  const [from, setFrom] = useState(new Date().toISOString().slice(0, 8) + "01");
  const [msg, setMsg] = useState("");
  useEffect(() => {
    setRegime(String(cur.regime || "Другая СНО")); setRate(String(Number(cur.rate || 0) * 100));
    setVat(String(Number(cur.vat_rate || 0) * 100)); setVatWb(String(Number(cur.vat_deduct_wb || 0) * 100));
    setCostVat(!!cur.cost_vat);
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps
  const num = (s: string) => Number(s.replace(",", ".")) / 100;
  return (
    <div className="chart tax-form">
      <b>Система налогообложения</b>
      <label>Режим <select value={regime} onChange={(e) => setRegime(e.target.value)}>
        {(data.regimes || []).map((r) => <option key={r}>{r}</option>)}</select></label>
      <label>Налоговая ставка, % <input value={rate} onChange={(e) => setRate(e.target.value)} /></label>
      <label>Ставка НДС, % <input value={vat} onChange={(e) => setVat(e.target.value)} /></label>
      <label>НДС к вычету Wildberries, % <input value={vatWb} onChange={(e) => setVatWb(e.target.value)} /></label>
      <label title="Для ОСНО: закупка с НДС — входящий НДС проданного товара уменьшает НДС к уплате"><input type="checkbox" checked={costVat}
        onChange={(e) => setCostVat(e.target.checked)} /> Себестоимость с НДС (НДС к вычету)</label>
      <label>Действует с <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
      <button onClick={() => api.setTax(shop, { regime, rate: num(rate), vat_rate: num(vat), vat_deduct_wb: num(vatWb), cost_vat: costVat, valid_from: from })
        .then(() => { setMsg("Сохранено. Пересчёт — сразу во всех вкладках."); onSaved(); }).catch((e) => setMsg("Ошибка: " + e.message))}>Сохранить</button>
      {msg && <span className="hint">{msg}</span>}
      <span className="hint">Прошлые периоды считаются по настройке, действовавшей тогда (история — в таблице ниже).</span>
    </div>
  );
}
