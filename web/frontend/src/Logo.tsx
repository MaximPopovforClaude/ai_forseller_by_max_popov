export function Logo({ kind = "horizontal", height }: {kind?: "horizontal" | "vertical" | "mark"; theme?: "light" | "dark"; height?: number}) {
  return <span className={"logo logo-" + kind} style={height ? {fontSize: height * .65} : undefined}>◫ Seller Analytics</span>;
}
