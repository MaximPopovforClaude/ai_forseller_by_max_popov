"""Self-hosted application component."""
import os
import subprocess
import sys
from collections import defaultdict
from datetime import date, timedelta

import stometric.web  
from stometric import ai_tasks, entry_views
from stometric.config import today_msk
from stometric.db import connect
from stometric.exclusions import excluded

shop = int(sys.argv[1])
D = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else today_msk()
Y = D - timedelta(days=1)
c = connect(readonly=True)
out = []
P = out.append
f0 = lambda v: f"{float(v or 0):,.0f}".replace(",", " ")  
acc = c.execute("SELECT coalesce(title, name) t FROM accounts WHERE id=%s", (shop,)).fetchone()["t"]
tax = c.execute("SELECT regime, rate, vat_rate FROM tax_settings WHERE account_id=%s ORDER BY valid_from DESC LIMIT 1", (shop,)).fetchone()
P(f"# ДОСЬЕ: {acc} (WB), задачи на {D:%d.%m.%Y}, разбор дня {Y:%d.%m.%Y}")
P(f"Налоги: {dict(tax) if tax else 'не заданы'}")


P("\n## Полнота данных")
have_entry = c.execute("SELECT 1 FROM entry_reports WHERE account_id=%s AND d_from=%s AND d_to=%s", (shop, Y, Y)).fetchone()
P(f"Точки входа за {Y:%d.%m}: {'есть' if have_entry else 'НЕТ (плагин ещё не выгрузил) — разделы и реклама/органика по точкам входа за вчера недоступны'}")
fu = c.execute("SELECT count(*) n FROM raw_rows WHERE account_id=%s AND source='funnel_day' AND row_date=%s", (shop, Y)).fetchone()["n"]
ads = c.execute("SELECT count(*) n FROM raw_rows WHERE account_id=%s AND source='ad_stats' AND row_date=%s", (shop, Y)).fetchone()["n"]
P(f"Воронка WB за {Y:%d.%m}: {fu} артикулов; статистика рекламы: {ads} кампаний")
try:
    h = subprocess.run([".venv/bin/python", "tools/health.py", "--print"], capture_output=True, text=True, timeout=120).stdout
    lines = [x.strip() for x in h.splitlines() if acc and acc.split()[0] in x]
    P("Сбор данных: " + ("; ".join(lines[:6]) if lines else "без замечаний"))
except Exception:  
    pass

ex = excluded(c, shop)
nom = {r["nm_id"]: r for r in c.execute("SELECT nm_id, imt_id, vendor_code, subject, title FROM nomenclature WHERE account_id=%s", (shop,))}


P("\n## Магазин по дням (воронка WB, без «не в работе»): заказы шт / ₽ / переходы / корзины")
sh = defaultdict(lambda: [0.0] * 4)
fn = defaultdict(dict)
for r in c.execute("""SELECT split_part(row_key,'|',1)::bigint nm, row_date d, data FROM raw_rows WHERE account_id=%s AND source='funnel_day'
                      AND row_date BETWEEN %s AND %s""", (shop, Y - timedelta(days=13), Y)):
    if r["nm"] in ex:
        continue
    dd = r["data"] or {}
    v = [float(dd.get(k) or 0) for k in ("orderCount", "orderSum", "openCount", "cartCount")]
    for i in range(4):
        sh[r["d"]][i] += v[i]
    fn[r["nm"]][r["d"]] = v
for d in sorted(sh):
    s = sh[d]
    P(f"  {d:%d.%m} {d:%a}: {s[0]:.0f} шт / {f0(s[1])} ₽ / {s[2]:.0f} переходов / {s[3]:.0f} корзин")


try:
    ev = entry_views.build(c, shop, days=8, grain="day", top_n=0)
    P("\n## Точки входа: магазин по дням (показы / переходы / корзины / заказы по отчёту WB; реклама — из статистики рекламы, органика = всего − реклама)")
    for d in ev.get("days") or []:
        m = (ev["funnel"]["total"] or {}).get(d)
        if m:
            P(f"  {d[8:]}.{d[5:7]}: показы {f0(m['views'])} (рекл {f0(m.get('ad_views'))}, орг {f0(m.get('org_views'))}), переходы {f0(m['clicks'])} "
              f"(рекл {f0(m.get('ad_clicks'))}, орг {f0(m.get('org_clicks'))}), корзины {f0(m['carts'])}, заказы {f0(m['orders'])} "
              f"(рекл {f0(m.get('ad_orders'))}, орг {f0(m.get('org_orders'))}), CTR {100 * (m['ctr'] or 0):.2f} %")
    P("Разделы WB по дням (показы / переходы / заказы):")
    for s in ev.get("sources_days") or []:
        P(f"  [{s['section']}] " + " | ".join(f"{d[8:]}.{d[5:7]}: {f0(m['views'])}/{f0(m['clicks'])}/{f0(m['orders'])}" for d, m in sorted(s["days"].items())))
except Exception as e:  
    c.rollback()
    P(f"(точки входа не собраны: {e})")


P(f"\n## Все артикулы с движением: {Y:%d.%m} против {Y - timedelta(days=1):%d.%m} и среднего {Y - timedelta(days=7):%d.%m}–{Y - timedelta(days=1):%d.%m}")
P("nm | артикул | предмет | заказы вчера / позавчера / среднее | ₽ вчера / позавчера | переходы вчера / позавчера / среднее | корзины вчера / позавчера")
rows = []
subj = defaultdict(lambda: [0.0] * 4)
for nm, dd in fn.items():
    g = lambda d, i: (dd.get(d) or [0, 0, 0, 0])[i]  
    avg = lambda i: sum(g(Y - timedelta(days=k), i) for k in range(1, 8)) / 7  
    y0, y1 = g(Y, 0), g(Y - timedelta(days=1), 0)
    n = nom.get(nm) or {}
    sj = subj[n.get("subject") or "—"]
    sj[0] += y0; sj[1] += y1; sj[2] += avg(0); sj[3] += g(Y, 1) - g(Y - timedelta(days=1), 1)
    if y0 or y1 or avg(0) >= 0.5:
        rows.append((abs(g(Y, 1) - g(Y - timedelta(days=1), 1)) + abs(y0 - avg(0)) * 300, nm, n, y0, y1, avg(0), g(Y, 1), g(Y - timedelta(days=1), 1),
                     g(Y, 2), g(Y - timedelta(days=1), 2), avg(2), g(Y, 3), g(Y - timedelta(days=1), 3)))
rows.sort(key=lambda x: -x[0])
for x in rows[:70]:
    _, nm, n, *v = x
    P(f"  {nm} | {n.get('vendor_code')} | {n.get('subject')} | {v[0]:.0f} / {v[1]:.0f} / {v[2]:.1f} | {f0(v[3])} / {f0(v[4])} | "
      f"{v[5]:.0f} / {v[6]:.0f} / {v[7]:.0f} | {v[8]:.0f} / {v[9]:.0f}")
P(f"(всего артикулов с заказами или движением: {len(rows)}; показаны 70 с наибольшим изменением)")
P("По предметам: заказы вчера / позавчера / среднее, Δ ₽ к позавчера")
for s, v in sorted(subj.items(), key=lambda kv: -abs(kv[1][3]))[:25]:
    if v[0] or v[1] or v[2]:
        P(f"  {s}: {v[0]:.0f} / {v[1]:.0f} / {v[2]:.1f}, Δ {f0(v[3])} ₽")


P("\n## Реклама")
stt = c.execute("SELECT balance, summary FROM ad_state WHERE account_id=%s", (shop,)).fetchone()
if stt:
    b, sm = stt["balance"] or {}, stt["summary"] or {}
    P(f"Баланс кабинета продвижения: {b}")
    if sm:
        P(f"Оплата рекламы за 14 дней по УПД (Кэшбэк = бонусы WB): {sm.get('upd_14d')}")
        P("Типы рекламы за 30 дней (расход весь / прибыль рекламы / на 1 ₽): " + "; ".join(
            f"{t.get('title')}: {f0(t['spend'])} / {f0(t['profit'])} / {t['roi']}" for t in sm.get("types") or []))
        P("Менеджеры за 30 дней: " + "; ".join(f"{t['key']}: {f0(t['spend'])} / {f0(t['profit'])} / {t['roi']}" for t in sm.get("managers") or []))
        P(f"Реклама на товары без себестоимости за 7 дней: {sm.get('nocost')}")
P("Реклама магазина по дням (расход весь, вкл. бонусы / из них бонусами, ₽):")
for r in c.execute("""SELECT day, sum(coalesce((data->>'ads')::numeric,0)) a, sum(coalesce((data->>'ads_bonus')::numeric,0)) b FROM agg_nm_day
                      WHERE account_id=%s AND day BETWEEN %s AND %s GROUP BY 1 ORDER BY 1""", (shop, Y - timedelta(days=7), Y)):
    P(f"  {r['day']:%d.%m}: {f0(r['a'])} / {f0(r['b'])}")
P("Предложения модуля «Реклама» (новые, код по правилам: окно 7 дн., безубыточная реклама на заказ = выкуп × прибыль с выкупа):")
for r in c.execute("""SELECT kind, advert_id, nm_id, query, reason, effect_week, priority FROM ad_proposals WHERE account_id=%s AND status='new'
                      ORDER BY priority DESC, effect_week DESC NULLS LAST LIMIT 40""", (shop,)):
    P(f"  [{r['kind']}, приоритет {r['priority']}, кампания {r['advert_id']}, арт. {r['nm_id']}{', «' + r['query'] + '»' if r['query'] else ''}"
      f"{', эффект ' + f0(r['effect_week']) + ' ₽/нед' if r['effect_week'] else ''}] {r['reason']}")
P("Применённые и отклонённые предложения рекламы за 7 дней:")
for r in c.execute("""SELECT p.kind, p.advert_id, p.nm_id, p.status, p.decided_at, o.verdict, o.delta_profit FROM ad_proposals p
                      LEFT JOIN ad_outcomes o ON o.proposal_id=p.id WHERE p.account_id=%s AND p.status IN ('applied','rejected')
                      AND p.decided_at > now() - interval '7 days' ORDER BY p.decided_at DESC LIMIT 30""", (shop,)):
    P(f"  {r['decided_at']:%d.%m %H:%M} {r['kind']} кампания {r['advert_id']} арт. {r['nm_id']}: {r['status']}"
      + (f", итог {r['verdict']} {f0(r['delta_profit'])} ₽/нед" if r["verdict"] else ""))
sys.stdout.write("\n".join(out) + "\n")
sys.stdout.flush()
out.clear()


P(f"\n## Подробное досье топ-15 артикулов за {Y - timedelta(days=7):%d.%m}–{Y:%d.%m} (по дням)")
sys.stdout.write("\n".join(out) + "\n")
sys.stdout.flush()
out.clear()
subprocess.run([".venv/bin/python", "tools/review/dossier.py", str(shop), "15", Y.isoformat(), "8"], env={**os.environ, "PYTHONPATH": "."}, timeout=1200)


P("\n## Задачи прошлых 7 дней: что было предложено, выполнено ли (автоотметка по журналу изменений), итог")
P(ai_tasks.history_digest(c, shop))
P("\n## Оценки и комментарии команды к задачам за 30 дней (учитывай: 👎 и комментарии — что команда считает плохими советами)")
P(ai_tasks.feedback_digest(c, shop))
P("\n## Оценки команды к предложениям модуля «Реклама» за 30 дней")
fb = c.execute("""SELECT f.rating, f.comment, f.snap->>'kind' k, f.snap->>'reason' r FROM ad_feedback f WHERE f.account_id=%s
                  AND f.updated_at > now() - interval '30 days' ORDER BY f.updated_at DESC LIMIT 30""", (shop,)).fetchall()
P("\n".join(f"  {'👍' if x['rating'] == 1 else '👎' if x['rating'] == -1 else '💬'} [{x['k']}] {(x['r'] or '')[:160]}" + (f" — {x['comment']}" if x["comment"] else "")
            for x in fb) or "  оценок пока нет")
sys.stdout.write("\n".join(out) + "\n")
