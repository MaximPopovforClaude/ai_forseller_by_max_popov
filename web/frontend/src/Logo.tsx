/** Original AI-100metric by Max Popov identity, including both color themes. */
export function Logo({ kind = "horizontal", theme, height }: { kind?: "horizontal" | "vertical" | "mark"; theme?: "light" | "dark"; height?: number }) {
  const t = theme || (document.documentElement.dataset.theme === "dark" ? "dark" : "light");
  const src = kind === "mark" ? `/brand/mark-${t}.svg` : `/brand/ai-100metric-${kind}-${t}.svg`;
  return <img src={src} alt="AI-100metric by Max Popov" className={"logo logo-" + kind} style={height ? { height } : undefined} />;
}
