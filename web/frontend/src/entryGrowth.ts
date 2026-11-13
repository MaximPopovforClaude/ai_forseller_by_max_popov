/** Relative growth of the same displayed metric in adjacent periods. */
export function growthThreshold(raw: string | null): number | null {
  if (raw == null || !raw.trim()) return null;
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 ? value : null;
}

export function declineThreshold(raw: string | null): number | null {
  const value = growthThreshold(raw);
  return value != null && value <= 100 ? value : null;
}

export function growthCell(a: number | null | undefined, b: number | null | undefined,
  threshold: number | null, baseClass = ""): { className: string; title?: string } {
  if (threshold == null || !Number.isFinite(threshold) || threshold <= 0 ||
      a == null || b == null || !Number.isFinite(a) || !Number.isFinite(b) || b <= 0 || a <= b)
    return { className: baseClass };
  const growth = (a - b) / b * 100;
  // Ratios such as 0.3 / 0.1 can be a few machine epsilons below the boundary.
  const tolerance = Number.EPSILON * Math.max(1, Math.abs(growth), threshold) * 8;
  if (!Number.isFinite(growth) || growth + tolerance < threshold) return { className: baseClass };
  return { className: [baseClass, "entry-growth"].filter(Boolean).join(" "),
    title: `Рост +${growth.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} % к предыдущему периоду (относительное изменение)` };
}

/** Growth is inclusive; decline is strictly greater than its own threshold. */
export function changeCell(a: number | null | undefined, b: number | null | undefined,
  growth: number | null, decline: number | null, baseClass = ""): { className: string; title?: string } {
  const up = growthCell(a, b, growth, baseClass);
  if (up.title) return up;
  if (decline == null || !Number.isFinite(decline) || decline <= 0 || decline > 100 ||
      a == null || b == null || !Number.isFinite(a) || !Number.isFinite(b) || b <= 0 || a < 0 || a >= b)
    return { className: baseClass };
  const drop = (b - a) / b * 100;
  const tolerance = Number.EPSILON * Math.max(1, drop, decline) * 8;
  if (!Number.isFinite(drop) || drop <= decline + tolerance) return { className: baseClass };
  return { className: [baseClass, "entry-decline"].filter(Boolean).join(" "),
    title: `Падение −${drop.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} % к предыдущему периоду (относительное изменение)` };
}
