"""Self-hosted application component."""

import io
import re
from datetime import date, datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

INT, NUM, PCT = "#,##0", "#,##0.00", "0.00%"
BOLD = Font(bold=True)
HEAD_FILL = PatternFill("solid", fgColor="E5E7EB")


def literal_cell(ws, row: int, column: int, value):
    """Data exports contain no formulas, including user-provided labels/headers."""
    cell = ws.cell(row, column, value)
    if isinstance(value, str):
        cell.data_type = "s"
    return cell


def _groups(cols: list[dict]) -> list[str | None]:
    """Подпись группы над столбцом — как на сайте: действует до следующей подписи; столбец без ключа group — вне групп."""
    out, cur = [], None
    for c in cols:
        if "group" not in c or c["group"] is None:
            out.append(None)
            continue
        if c["group"]:
            cur = c["group"]
        out.append(cur)
    return out


def _cell(col: dict, row: dict, v):
    """(значение, формат) ячейки Excel по типу столбца сайта."""
    t, f = col.get("type") or "text", col["field"]
    if v is None or v == "":
        return None, None
    if isinstance(v, (list, dict)):
        return str(v), None
    if t in ("int", "money", "num", "pct", "share", "rowfmt", "change", "edit_money") and not isinstance(v, (int, float)):
        try:
            v = float(str(v).replace(",", ".").replace(" ", ""))
        except ValueError:
            return str(v), None
    if t in ("int", "money"):
        return v, "0" if f.endswith("_id") or f == "nm_id" else INT
    if t in ("num", "edit_money"):
        return v, NUM
    if t == "pct":
        return v / 100, PCT
    if t == "share":
        return v, PCT
    if t == "rowfmt":
        fmt = row.get("fmt")
        if fmt == "h":
            return None, None
        return v, PCT if fmt == "pct" else NUM if fmt == "num" else INT
    if t == "change":
        if row.get("fmt") == "h":
            return None, None
        return (v * 100, '+0.00" п.п.";-0.00" п.п.";0') if row.get("fmt") == "pct" else (v, "+0%;-0%;0%")
    if t == "date":
        try:
            return date.fromisoformat(str(v)[:10]), "DD.MM.YYYY"
        except ValueError:
            return str(v), None
    if t == "datetime":
        try:
            d = datetime.fromisoformat(str(v))
            return d.replace(tzinfo=None), "DD.MM.YYYY HH:MM"
        except ValueError:
            return str(v), None
    return v if isinstance(v, (int, float)) else str(v), None


def build(res: dict, fields: list[str] | None = None, title: str = "") -> bytes:
    cols = [c for c in res.get("columns") or [] if c.get("field")]
    if fields:                                   
        by = {c["field"]: c for c in cols}
        cols = [by[f] for f in fields if f in by] or cols
    rows = res.get("rows") or []
    total = res.get("total_row")
    colors = res.get("cell_colors") or {}

    wb = Workbook()
    ws = wb.active
    ws.title = re.sub(r"[\[\]:*?/\\]", " ", title or res.get("title") or "Лист")[:31] or "Лист"
    groups = _groups(cols)
    r0 = 1
    if any(groups):
        for j, g in enumerate(groups, 1):
            if g and (j == 1 or groups[j - 2] != g):
                literal_cell(ws, 1, j, g).font = BOLD
        i = 0                                    
        while i < len(groups):
            k = i
            while k + 1 < len(groups) and groups[k + 1] == groups[i]:
                k += 1
            if groups[i] and k > i:
                ws.merge_cells(start_row=1, start_column=i + 1, end_row=1, end_column=k + 1)
            ws.cell(1, i + 1).alignment = Alignment(horizontal="center")
            i = k + 1
        r0 = 2
    for j, c in enumerate(cols, 1):
        h = literal_cell(ws, r0, j, c.get("title") or c["field"])
        h.font, h.fill = BOLD, HEAD_FILL
        h.alignment = Alignment(wrap_text=True, vertical="top")

    def put(r: int, row, bold=False):
        for j, c in enumerate(cols, 1):
            v = row.get(c["field"]) if isinstance(row, dict) else (row[j - 1] if j - 1 < len(row) else None)
            val, fmt = _cell(c, row if isinstance(row, dict) else {}, v)
            if val is None:
                if bold or (isinstance(row, dict) and row.get("fmt") == "h"):
                    ws.cell(r, j).font = BOLD
                continue
            x = literal_cell(ws, r, j, val)
            if c.get("type") == "image" and str(val).startswith("http"):    
                x.value, x.hyperlink, x.font = "фото", str(val), Font(color="2563EB", underline="single")
            if fmt:
                x.number_format = fmt
            if bold or (isinstance(row, dict) and row.get("fmt") == "h"):
                x.font = BOLD
            m = colors.get(c["field"])
            if m and str(v) in m:
                x.fill = PatternFill("solid", fgColor=m[str(v)].lstrip("#")[:6].upper())

    r = r0 + 1
    for row in rows:
        put(r, row)
        r += 1
    if total:
        put(r, total, bold=True)

    for j, c in enumerate(cols, 1):            
        t = c.get("type") or "text"
        lens = [len(str(c.get("title") or ""))] + [len(str(x.get(c["field"]) or "")) for x in rows[:200] if isinstance(x, dict)]
        w = 60 if t == "label" else min(50, max(10, max(lens) + 2)) if t in ("text", "edit_text") else min(22, max(11, max(lens[1:] or [0]) + 4))
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.row_dimensions[r0].height = 45
    first_label = 1 if cols and (cols[0].get("type") == "label") else 0
    ws.freeze_panes = ws.cell(r0 + 1, 1 + first_label)
    if rows and res.get("layout") != "sheet":
        ws.auto_filter.ref = f"A{r0}:{get_column_letter(len(cols))}{r0 + len(rows)}"
    note = res.get("note")
    if note and isinstance(note, str):
        literal_cell(ws, r + 2 + (1 if total else 0), 1, note).font = Font(italic=True, color="6B7280")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def filename(shop_name: str, title: str, d1: date | None, d2: date | None) -> str:
    s = f"{shop_name} — {title}" + (f" {d1:%d.%m}–{d2:%d.%m.%Y}" if d1 and d2 else "")
    return re.sub(r'[\\/:*?"<>|#]+', " ", s).strip()[:150] + ".xlsx"
