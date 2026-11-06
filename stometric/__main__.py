"""Командная строка Seller Analytics.

  python -m stometric migrate
  python -m stometric account-add <name> <TOKEN_ENV> [заголовок]
  python -m stometric collect <account> <сборщик|all> [...]
  python -m stometric status <account>
"""

import json
import sys
from pathlib import Path

from . import db
from .collectors import Ctx, registry, run_one
from .wb import WB

MAX_PARALLEL = 2   

FIRST_LOAD = ["nomenclature", "tariffs", "prices", "stocks_wb", "stocks_seller", "stocks_wh", "stocks_report", "adverts", "orders", "sales",
              "funnel", "realization_daily", "ad_upd", "ad_stats", "realization", "paid_storage", "acceptance", "funnel_days"]


def main(argv):
    if not argv:
        print(__doc__)
        return
    cmd, *args = argv
    if cmd == "migrate":
        print("применены:", db.migrate() or "ничего нового")
    elif cmd == "account-add":
        name, token_env, *title = args
        with db.connect() as c:
            c.execute("INSERT INTO accounts(name,token_env,title) VALUES (%s,%s,%s) ON CONFLICT (name) DO UPDATE SET "
                      "token_env=EXCLUDED.token_env, title=COALESCE(EXCLUDED.title, accounts.title)",
                      (name, token_env, " ".join(title) or None))
        print("ok")
    elif cmd == "collect":
        name, *which = args
        with db.connect() as c:
            acc = db.account(c, name)
            if acc["marketplace"] == "ym":
                from . import collectors_ym as yc
                for n in (yc.FIRST_LOAD if which in ([], ["all"]) else which):
                    print(json.dumps(yc.run_one(c, acc, n), ensure_ascii=False, default=str), flush=True)
                return
            if acc["marketplace"] == "ozon":
                from . import collectors_ozon as oc
                for n in (oc.FIRST_LOAD if which in ([], ["all"]) else which):
                    print(json.dumps(oc.run_one(c, acc, n), ensure_ascii=False, default=str), flush=True)
                return
            ctx = Ctx(c, acc, WB(c, acc))
            names = list(registry()) if which in ([], ["all"]) else which
            for n in names:
                res = run_one(ctx, n)
                res.pop("trace", None) if res.get("ok") else None
                print(json.dumps(res, ensure_ascii=False, default=str))
    elif cmd == "collect-due":
        
        
        import os
        import subprocess
        root = str(Path(__file__).resolve().parents[1])
        env = {**os.environ, "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"}
        with db.connect() as c:
            
            
            shops = c.execute("""SELECT a.id, a.name FROM accounts a WHERE a.is_active
                                 ORDER BY (SELECT max(last_run_at) FROM collector_state s WHERE s.account_id=a.id AND s.collector NOT LIKE '\\_%%')
                                          NULLS FIRST, a.id""").fetchall()
        active = lambda u: subprocess.run(["systemctl", "--user", "is-active", "-q", u], env=env).returncode == 0  
        running = sum(active(f"ai-stometric-collect-{a['id']}") for a in shops)
        for acc in shops:
            unit = f"ai-stometric-collect-{acc['id']}"
            if active(unit):
                print(acc["name"], "— сбор ещё идёт, пропускаю", flush=True)
                continue
            if active(f"ai-stometric-rebuild-{acc['id']}"):     
                print(acc["name"], "— идёт пересчёт, сбор в следующий круг", flush=True)
                continue
            if running >= MAX_PARALLEL:                         
                print(acc["name"], "— уже идут", running, "сбора, в следующий круг", flush=True)
                continue
            running += 1
            r = subprocess.run(["systemd-run", "--user", "--collect", f"--unit={unit}", "--nice=10", "-p", "IOSchedulingClass=idle",
                                "-p", "MemoryMax=1500M", "-p", "RuntimeMaxSec=3h", f"--working-directory={root}",
                                sys.executable, "-m", "stometric", "collect-shop", acc["name"]], env=env, capture_output=True, text=True)
            print(acc["name"], "→", (r.stdout or r.stderr).strip()[:200], flush=True)
            if r.returncode != 0:          
                _collect_shop(acc["name"])
    elif cmd == "collect-shop":
        _collect_shop(args[0])
    elif cmd == "first-load":
        
        with db.connect() as c:
            acc = db.account(c, args[0])
            if acc["marketplace"] == "ym":
                from . import collectors_ym as yc
                for n in yc.FIRST_LOAD:
                    print(json.dumps(yc.run_one(c, acc, n), ensure_ascii=False, default=str), flush=True)
                return
            if acc["marketplace"] == "ozon":
                from . import collectors_ozon as oc
                names = oc.FIRST_LOAD + (list(oc.AD_COLLECTORS) if oc.has_ad_key(c, acc["id"]) else [])   
                for n in names:
                    print(json.dumps(oc.run_one(c, acc, n), ensure_ascii=False, default=str), flush=True)
                return
            ctx = Ctx(c, acc, WB(c, acc))
            for n in FIRST_LOAD:
                res = run_one(ctx, n)
                res.pop("trace", None)
                print(json.dumps(res, ensure_ascii=False, default=str), flush=True)
            from datetime import timedelta
            from . import loadplan
            from .config import today_msk
            from .materialize import build_nm_day, build_real_week
            if loadplan.shallow(c, acc["id"]):     
                print("nm_day 60д:", build_nm_day(c, acc["id"], today_msk() - timedelta(days=loadplan.SHALLOW_DAYS)), flush=True)
            else:
                print("nm_day:", build_nm_day(c, acc["id"]), "real_week:", build_real_week(c, acc["id"]), flush=True)
    elif cmd == "precompute":          
        import time
        from . import tabcache
        with db.connect() as c:
            accs = [db.account(c, args[0])] if args else c.execute("SELECT * FROM accounts WHERE is_active ORDER BY id").fetchall()
            for acc in accs:
                t0 = time.time()
                print(f"{acc['name']} (id {acc['id']}):", flush=True)
                tabcache.precompute(c, acc["id"], log=lambda s: print(s, flush=True))
                print(f"  итого {time.time() - t0:.0f} с", flush=True)
    elif cmd == "offsite-backup":      
        from . import offsite   
        f = args[0] if args else "latest"
        if f == "latest":
            fs = sorted(Path("data/backups").glob("ai_stometric_*.dump"))
            f = str(fs[-1]) if fs else ""
        with db.connect() as c:
            if not offsite.status(c)["configured"]:
                print("offsite: хранилище не настроено — пропуск")
            else:
                print("offsite:", offsite.run(c, Path(f)), flush=True)
    elif cmd == "service-news-add":    
        from . import web  
        from .api_service_news import add
        with db.connect() as c:
            print("новость", add(c, args[0], sys.stdin.read(), [x for x in (args[1] if len(args) > 1 else "").split(",") if x]))
            c.commit()
    elif cmd == "materialize":
        from .materialize import build_nm_day, build_real_week
        with db.connect() as c:
            acc = db.account(c, args[0])
            while True:            
                c.execute("UPDATE collector_state SET cursor='{}' WHERE account_id=%s AND collector='_rebuild'", (acc["id"],))
                c.commit()
                print("nm_day:", build_nm_day(c, acc["id"]), "real_week:", build_real_week(c, acc["id"]), flush=True)
                r = c.execute("SELECT cursor FROM collector_state WHERE account_id=%s AND collector='_rebuild'", (acc["id"],)).fetchone()
                if not (r and (r["cursor"] or {}).get("again")):
                    break
    elif cmd == "user-add":
        
        email, *opts = args
        kv = dict(o.split("=", 1) for o in opts if "=" in o)
        pw = sys.stdin.readline().strip() if not sys.stdin.isatty() else __import__("getpass").getpass("Пароль: ")
        if len(pw) < 10:
            sys.exit("Пароль короче 10 символов — не сохранён")
        from .auth import hash_password
        with db.connect() as c:
            uid = c.execute(
                "INSERT INTO users(email,password_hash,is_superadmin) VALUES (%s,%s,%s) ON CONFLICT (email) DO UPDATE SET "
                "password_hash=EXCLUDED.password_hash, is_superadmin=users.is_superadmin OR EXCLUDED.is_superadmin RETURNING id",
                (email.strip().lower(), hash_password(pw), "superadmin" in opts)).fetchone()["id"]
            c.execute("INSERT INTO memberships(user_id,workspace_id,role) VALUES (%s,%s,%s) ON CONFLICT (user_id,workspace_id) "
                      "DO UPDATE SET role=EXCLUDED.role", (uid, int(kv.get("ws", 1)), kv.get("role", "owner")))
            c.execute("INSERT INTO audit_log(user_id,workspace_id,action,details) VALUES (%s,%s,'user-add/password',%s)",
                      (uid, int(kv.get("ws", 1)), json.dumps({"email": email, "role": kv.get("role", "owner")})))
        print(f"✓ пользователь {email} (id {uid}) — пароль сохранён (хеш)")
    elif cmd == "status":
        with db.connect() as c:
            acc = db.account(c, args[0])
            for r in c.execute("SELECT collector,last_ok_at,last_run_at,left(last_error,200) err,cursor FROM collector_state "
                               "WHERE account_id=%s ORDER BY collector", (acc["id"],)):
                print(json.dumps(r, ensure_ascii=False, default=str))
    else:
        print(__doc__)



def _collect_shop(name: str) -> None:
    """Сборщики одного магазина, кому пора, затем агрегаты. Один процесс на магазин (advisory lock)."""
    with db.connect() as c:
        acc = db.account(c, name)
        if not c.execute("SELECT pg_try_advisory_lock(%s) ok", (424242000 + acc["id"],)).fetchone()["ok"]:
            print(name, "уже идёт сбор этого магазина — выходим", flush=True)
            return
        if acc["marketplace"] == "ym":
            from . import collectors_ym as yc
            for n in yc.due(c, acc["id"]):
                res = yc.run_one(c, acc, n)
                res.pop("trace", None)
                print(acc["name"], json.dumps(res, ensure_ascii=False, default=str), flush=True)
            return
        if acc["marketplace"] == "ozon":
            from . import collectors_ozon as oc
            for n in oc.due(c, acc["id"]):
                res = oc.run_one(c, acc, n)
                res.pop("trace", None)
                print(acc["name"], json.dumps(res, ensure_ascii=False, default=str), flush=True)
            return
        from .schedule import due
        ctx = Ctx(c, acc, WB(c, acc))
        ran = set()
        for n in due(c, acc["id"]):
            res = run_one(ctx, n)
            res.pop("trace", None)
            if res.get("ok"):
                ran.add(n)
            print(acc["name"], json.dumps(res, ensure_ascii=False, default=str), flush=True)
        from .materialize import after_collect
        try:
            print(acc["name"], "агрегаты:", after_collect(c, acc["id"], ran), flush=True)
        except Exception as e:  
            c.rollback()
            print(acc["name"], "агрегаты: ошибка", type(e).__name__, str(e)[:300], flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
