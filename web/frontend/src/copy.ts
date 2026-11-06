/** Клик по артикулу — скопировать значение, всплывашка «Скопировано» у курсора . */
export function copyCell(v: unknown, ev?: Event | null) {
  const t = v == null ? "" : String(v);
  if (!t) return;
  const toast = () => {
    const d = document.createElement("div");
    d.className = "copy-toast"; d.textContent = `Скопировано: ${t.length > 40 ? t.slice(0, 40) + "…" : t}`;
    const me = ev as MouseEvent | undefined;
    if (me?.clientX) { d.style.left = `${me.clientX + 8}px`; d.style.top = `${me.clientY - 34}px`; }
    document.body.appendChild(d); setTimeout(() => d.remove(), 1300);
  };
  if (navigator.clipboard) navigator.clipboard.writeText(t).then(toast).catch(() => {});
  else { const a = document.createElement("textarea"); a.value = t; document.body.appendChild(a); a.select(); document.execCommand("copy"); a.remove(); toast(); }
}
