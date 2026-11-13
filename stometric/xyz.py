"""Stability of daily WB order quantities; existing ABC formulas stay unchanged."""
from datetime import date, timedelta
from math import sqrt, isfinite

from .config import today_msk

NOTE = ("XYZ — стабильность количества заказов по полным календарным дням: "
        "CV = стандартное отклонение / среднее; X ≤ 10 %, Y ≤ 25 %, Z > 25 %. "
        "Нулевые дни включены. Нужно минимум 7 дней и покрытие периода готовыми итогами; "
        "новые товары и периоды без заказов — без класса. Сегодня исключено. "
        "Акции, сезонность и отсутствие остатков могут повышать CV; это не прогноз спроса.")
COLORS = {"X": "#bbf7d0", "Y": "#fef08a", "Z": "#fecaca"}


def classify(n, total, squares, *, complete=True, invalid=False):
    result = {"xyz": None, "xyz_cv": None, "xyz_days": n, "xyz_status": ""}
    if not complete:
        result["xyz_status"] = "Неполная история"
    elif n < 7:
        result["xyz_status"] = "Нужно минимум 7 дней"
    elif invalid or not all(isfinite(float(v)) for v in (total, squares)) or total < 0 or squares < 0:
        result["xyz_status"] = "Некорректные данные"
    elif not total:
        result["xyz_status"] = "Нет заказов"
    else:
        mean = float(total) / n
        cv = sqrt(max(0.0, float(squares) / n - mean * mean)) / mean
        result.update(xyz="X" if cv <= .10 + 1e-12 else "Y" if cv <= .25 + 1e-12 else "Z",
                      xyz_cv=cv, xyz_status="Рассчитано")
    return result


def orders(c, shop, start, end, nms):
    """One bounded aggregate query. Missing rows inside covered history are zero days."""
    if not nms:
        return {}
    end = min(end, today_msk() - timedelta(days=1))
    n = max(0, (end - start).days + 1)
    state = c.execute("SELECT covered_from, covered_to FROM agg_state WHERE account_id=%s AND name='nm_day'", (shop,)).fetchone()
    complete = bool(state and state['covered_from'] and state['covered_to'] and
                    state['covered_from'] <= start and state['covered_to'] >= end)
    data = {r['nm_id']: r for r in c.execute("""
        SELECT nm_id, sum(coalesce((data->>'orders')::numeric,0)) total,
               sum(power(coalesce((data->>'orders')::numeric,0),2)) squares,
               bool_or((data->>'orders')::numeric < 0) invalid
        FROM agg_nm_day WHERE account_id=%s AND day BETWEEN %s AND %s AND nm_id=ANY(%s)
        GROUP BY nm_id""", (shop, start, end, list(nms)))} if n else {}
    created = {}
    for r in c.execute("SELECT nm_id, data->>'createdAt' created FROM nomenclature WHERE account_id=%s AND nm_id=ANY(%s)", (shop, list(nms))):
        try:
            created[r['nm_id']] = date.fromisoformat((r['created'] or '')[:10])
        except ValueError:
            pass
    out = {}
    for nm in nms:
        r = data.get(nm) or {}
        fresh = nm in created and created[nm] > start
        out[nm] = classify(n, r.get('total') or 0, r.get('squares') or 0,
                           complete=complete and not fresh, invalid=r.get('invalid', False))
        if fresh:
            out[nm]['xyz_status'] = 'Товар создан внутри периода'
    return out
