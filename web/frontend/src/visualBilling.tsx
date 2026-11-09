import { useState } from "react";
import { http } from "./api";

export type RenderModel = { id: string; title: string; provider: string; ready: boolean; default?: boolean; why: string | null };
export type RenderEstimate = { total: number | null; by_model: Record<string, {
  title: string; one: number | null; n: number; sum: number | null; unit: "USD" | "credits" | "subscription"; note: string;
}> };

export function estimateText(e: RenderEstimate): string {
  return Object.values(e.by_model).map(m => m.unit !== "credits"
    ? `${m.title}: ${m.n} шт. ${m.note}`
    : `${m.title}: ${m.n} шт., ${m.sum === null ? "стоимость неизвестна" : `≈ ${m.sum} кредитов Higgsfield`}`
  ).join("\n");
}

/** An explicit choice (including clearing all boxes) survives catalog refreshes. */
export function useRenderSelection(scope: string, models?: RenderModel[]): [string[], (ids: string[]) => void] {
  const [choice, setChoice] = useState<{scope: string; ids: string[]} | null>(null);
  const ids = choice?.scope === scope ? choice.ids : (models ?? []).filter(m => m.default && m.ready).map(m => m.id);
  return [ids, next => setChoice({scope, ids: next})];
}

export function modelsReady(models: RenderModel[], ids: string[]): boolean {
  return ids.length > 0 && ids.every(id => models.some(m => m.id === id && m.ready));
}

export function RenderModels({ models, value, onChange, disabled = false }: {
  models: RenderModel[]; value: string[]; onChange: (v: string[]) => void; disabled?: boolean;
}) {
  const personal = models.find(m => m.provider === "chatgpt");
  return <><div className="rnp-bar"><span>Нейросеть:</span>{models.map(m => <label key={m.id} title={m.why || ""}>
    <input type="checkbox" checked={value.includes(m.id)} disabled={disabled || !m.ready}
      onChange={() => onChange(value.includes(m.id) ? value.filter(x => x !== m.id) : [...value, m.id])} /> {m.title}
  </label>)}</div>
  {personal && !personal.ready && <div className="hint">{personal.why}</div>}
  {personal && value.includes(personal.id) && <div className="hint">Отрисовка использует лимит личной подписки ChatGPT.</div>}
  {!personal && !models.some(m => m.ready) && <div className="hint">Подключите ключ GPT Image или аккаунт Higgsfield в «Настройках аккаунта».</div>}
  {value.some(id => models.find(m => m.id === id)?.provider === "openai") && <div className="hint">
    Оплата со счёта OpenAI API по фактическому расходу; точная сумма до генерации неизвестна. Формат 1152 × 1536, качество high.{" "}
    <a href="https://developers.openai.com/api/docs/pricing" target="_blank" rel="noreferrer">Тарифы OpenAI</a>
  </div>}</>;
}

/** Every retouch entry point shows the actual provider's billing before sending. */
export async function confirmRetouch(url: string, models: string[], count: number): Promise<boolean> {
  const e = await http.post<RenderEstimate>(`${url}/render/estimate`, { models, edit_n: count });
  return window.confirm(`${estimateText(e)}\n\nЗапустить доработку?`);
}
