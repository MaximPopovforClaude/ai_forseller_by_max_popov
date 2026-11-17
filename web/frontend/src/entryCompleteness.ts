/** Partial observations stay visible, but never become complete totals/trends. */
export type Completeness = { partial?: string[]; ad_partial?: string[]; org_partial?: string[];
  payment?: Partial<Record<'cpm' | 'cpc' | 'unknown', Completeness>> };
export function partialValue(m: Completeness | undefined, key: string): boolean {
  const payment = /^payment_(cpm|cpc|unknown)_(.+)$/.exec(key);
  if (payment) return partialValue(m?.payment?.[payment[1] as 'cpm' | 'cpc' | 'unknown'], payment[2]);
  const split = /^(ad|org)_(.+)$/.exec(key);
  return split ? !!m?.[`${split[1]}_partial` as 'ad_partial' | 'org_partial']?.includes(split[2]) : !!m?.partial?.includes(key);
}
export const PARTIAL_NOTE = 'Неполные данные: сумма доступных значений, не полный итог. Для органики — оценка по неполной рекламе.';
