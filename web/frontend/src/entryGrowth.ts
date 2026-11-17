import type { CSSProperties } from "react";

type Cell = { className: string; title?: string; style?: CSSProperties };

/** Suppress the isolated 1 → 0 signal, without rounding small values into it. */
export const singleToZero = (a: number | null | undefined, b: number | null | undefined, scale = 1) =>
  a === 0 && b != null && b * scale === 1;

function shade(percent: number, up: boolean): CSSProperties {
  // Fixed scales keep the same change the same shade when the threshold changes.
  // Growth has no upper bound; decline is limited to 100% for nonnegative metrics.
  const strength = up ? 1 - 300 / (300 + percent) : percent / 100;
  const mix = (from: number[], to: number[]) => from.map((v, i) => Math.round(v + (to[i] - v) * strength));
  const light = up ? mix([220, 252, 231], [20, 83, 45]) : mix([254, 226, 226], [127, 29, 29]);
  const dark = up ? mix([37, 84, 55], [8, 29, 17]) : mix([115, 48, 59], [38, 8, 14]);
  const linear = light.map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
  const luminance = linear[0] * .2126 + linear[1] * .7152 + linear[2] * .0722;
  return { "--entry-fill-light": `rgb(${light.join(", ")})`, "--entry-fill-dark": `rgb(${dark.join(", ")})`,
    "--entry-ink": luminance > .179 ? "#000" : "#fff" } as CSSProperties;
}

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
  growth: number | null, decline: number | null, baseClass = "", gradient = false, scale = 1): Cell {
  const up = growthCell(a, b, growth, baseClass);
  if (up.title) return gradient ? { ...up, style: shade((a! - b!) / b! * 100, true) } : up;
  if (decline == null || !Number.isFinite(decline) || decline <= 0 || decline > 100 ||
      a == null || b == null || !Number.isFinite(a) || !Number.isFinite(b) || b <= 0 || a < 0 || a >= b || singleToZero(a, b, scale))
    return { className: baseClass };
  const drop = (b - a) / b * 100;
  const tolerance = Number.EPSILON * Math.max(1, drop, decline) * 8;
  if (!Number.isFinite(drop) || drop <= decline + tolerance) return { className: baseClass };
  return { className: [baseClass, "entry-decline"].filter(Boolean).join(" "),
    ...(gradient ? { style: shade(drop, false) } : {}),
    title: `Падение −${drop.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} % к предыдущему периоду (относительное изменение)` };
}
