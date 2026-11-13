"""Клиент Ozon Performance API (api-performance.ozon.ru) — рекламный кабинет: только чтение, журнал api_log, лимиты через api_rate.

Ключ — пара Client ID + Client Secret (ЛК Ozon → Продвижение → Настройки → API), в account_ad_tokens.enc лежит шифротекст
JSON {"client_id","client_secret"}. По ним берём временный токен (POST /api/client/token, живёт ~30 мин) и дальше — только GET
из белого списка READ_PATHS.

Ответы статистики Ozon отдаёт то JSON, то CSV (разделитель «;», числа с запятой) — разбираем оба (rows()).
"""

import csv
import io
import json
import re
import time
from datetime import datetime, timedelta, timezone

import httpx

from .wb import RateLimited
from .api_log_params import encode as log_params

HOST = "https://api-performance.ozon.ru"
TOKEN_PATH = "/api/client/token"
READ_PATHS = re.compile(r"^/api/client/(campaign|campaign/\d+/objects|statistics/(daily|expense)(/json)?|statistics/[0-9a-f-]{36}|statistics/report)$")
REPORT_PATH = "/api/client/statistics"      
PHRASES_PATH = "/api/client/statistics/phrases"   
INTERVAL = 1.0


class OzonPerfError(RuntimeError):
    pass


def _token(client_id: str, client_secret: str) -> tuple[str | None, str | None]:
    try:
        r = httpx.post(HOST + TOKEN_PATH, json={"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"},
                       headers={"Accept": "application/json"}, timeout=30)
    except httpx.HTTPError as e:
        return None, f"Ozon не ответил: {type(e).__name__} — попробуйте позже"
    if r.status_code in (400, 401, 403):
        return None, "Ozon не принял рекламный ключ: проверьте Client ID и Client Secret (ЛК Ozon → Продвижение → Настройки → API)"
    if r.status_code != 200:
        return None, f"Ozon ответил {r.status_code}: {r.text[:160]}"
    tok = (r.json() or {}).get("access_token")
    return (tok, None) if tok else (None, "Ozon не выдал токен по этому ключу")


def check(client_id: str, client_secret: str) -> dict:
    """Проверка рекламного ключа до сохранения: токен + список кампаний."""
    client_id, client_secret = str(client_id or "").strip(), str(client_secret or "").strip()
    if not client_id or not client_secret:
        return {"error": "Нужны оба поля рекламного ключа: Client ID и Client Secret"}
    tok, err = _token(client_id, client_secret)
    if err:
        return {"error": err}
    try:
        r = httpx.get(HOST + "/api/client/campaign", headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"}, timeout=30)
    except httpx.HTTPError as e:
        return {"error": f"Ozon не ответил: {type(e).__name__} — попробуйте позже"}
    if r.status_code != 200:
        return {"error": f"Ключ принят, но список кампаний не отдан: {r.status_code} {r.text[:160]}"}
    lst = (r.json() or {}).get("list") or []
    return {"campaigns": len(lst), "running": sum(1 for x in lst if x.get("state") == "CAMPAIGN_STATE_RUNNING"),
            "client_id_tail": client_id[-6:]}


def num(v):
    """Число из ответа Ozon: 1234.5 | "1234,50" | "1 234,5" | "" → float | None."""
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def rows(data, header_hint: str = "") -> list[dict]:
    """Строки статистики из JSON ({"rows": [...]}, список) или CSV-текста. header_hint — слово, по которому узнаём строку заголовка
    (над ней Ozon пишет строку-описание отчёта)."""
    if isinstance(data, dict):
        for k in ("rows", "list", "result", "data"):
            if isinstance(data.get(k), list):
                return data[k]
        return []
    if isinstance(data, list):
        return data
    text = str(data or "").lstrip("﻿")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    start = next((i for i, ln in enumerate(lines) if ";" in ln and header_hint.lower() in ln.lower()), None)
    if start is None:
        start = next((i for i, ln in enumerate(lines) if ";" in ln), 0)    
    return list(csv.DictReader(io.StringIO("\n".join(lines[start:])), delimiter=";"))


class OzonPerf:
    def __init__(self, conn, account: dict):
        from .vault import decrypt
        self.c = conn
        self.acc = account
        row = conn.execute("SELECT enc FROM account_ad_tokens WHERE account_id=%s", (account["id"],)).fetchone()
        if not row:
            raise OzonPerfError("у магазина нет рекламного ключа Ozon")
        d = json.loads(decrypt(row["enc"]))
        self.cid, self.secret = str(d["client_id"]).strip(), str(d["client_secret"]).strip()
        self.http = httpx.Client(timeout=120)
        self.tok, self.tok_until = None, 0.0

    def _auth(self) -> dict:
        if not self.tok or time.time() > self.tok_until:
            tok, err = _token(self.cid, self.secret)
            if err:
                raise OzonPerfError(err)
            self.tok, self.tok_until = tok, time.time() + 25 * 60
        return {"Authorization": f"Bearer {self.tok}", "Accept": "application/json"}

    def _wait_slot(self, bucket: str, max_wait: float = 120):
        row = self.c.execute(
            "INSERT INTO api_rate(account_id,bucket,next_allowed) VALUES (%s,%s,now()) "
            "ON CONFLICT (account_id,bucket) DO UPDATE SET bucket=EXCLUDED.bucket RETURNING next_allowed",
            (self.acc["id"], bucket)).fetchone()
        self.c.commit()
        wait = (row["next_allowed"] - datetime.now(timezone.utc)).total_seconds()
        if wait > max_wait:
            raise RateLimited(bucket, row["next_allowed"])
        if wait > 0:
            time.sleep(wait)
        self.c.execute("UPDATE api_rate SET next_allowed=%s WHERE account_id=%s AND bucket=%s",
                       (datetime.now(timezone.utc) + timedelta(seconds=INTERVAL), self.acc["id"], bucket))
        self.c.commit()

    def report(self, campaign_id: int, date_from: str, date_to: str, wait_s: int = 300, phrases: bool = False) -> str:
        """Асинхронный отчёт по одной кампании (по дням): заказ → ожидание готовности → CSV-текст. phrases — поисковые фразы."""
        self._wait_slot("ozperf")
        r = self.http.post(HOST + (PHRASES_PATH if phrases else REPORT_PATH), headers={**self._auth(), "Content-Type": "application/json"},
                           json={"campaigns": [str(campaign_id)], "dateFrom": date_from, "dateTo": date_to, "groupBy": "DATE"})
        self.c.execute("INSERT INTO api_log(account_id,method,params,status,rows,error,duration_ms) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                       (self.acc["id"], "ozperf:" + REPORT_PATH, json.dumps({"campaign": campaign_id, "from": date_from, "to": date_to}),
                        r.status_code, None, None if r.status_code == 200 else r.text[:500], 0))
        self.c.commit()
        if r.status_code == 429:
            raise RateLimited("ozperf:report", datetime.now(timezone.utc) + timedelta(minutes=5))
        if r.status_code != 200:
            raise OzonPerfError(f"Ozon Performance отчёт: {r.status_code} {r.text[:300]}")
        uuid = (r.json() or {}).get("UUID") or (r.json() or {}).get("uuid")
        t0 = time.time()
        while time.time() - t0 < wait_s:
            time.sleep(5)
            st = self.get(f"/api/client/statistics/{uuid}") or {}
            state = st.get("state") if isinstance(st, dict) else None
            if state == "OK":
                return self.get("/api/client/statistics/report", {"UUID": uuid})
            if state in ("ERROR", "CANCELLED"):
                raise OzonPerfError(f"Ozon не построил отчёт по кампании {campaign_id}: {st}")
        raise OzonPerfError(f"Отчёт по кампании {campaign_id} не готов за {wait_s} с")

    def get(self, path: str, params: dict | None = None, allow_404: bool = False):
        """GET из белого списка. Возвращает разобранный JSON или текст (CSV); None — если allow_404 и метода нет."""
        base = path.split("?")[0]
        if not READ_PATHS.match(base):
            raise OzonPerfError(f"GET {path}: не в списке методов только для чтения — запрещено")
        bucket = "ozperf"
        status, err = None, None
        for attempt in range(4):
            self._wait_slot(bucket)
            t0 = time.time()
            err, status, data = None, None, None
            try:
                r = self.http.get(HOST + path, params=params, headers=self._auth())
                status = r.status_code
                if status == 200:
                    data = r.json() if "json" in r.headers.get("content-type", "") else r.text
                elif status == 401 and attempt == 0:
                    self.tok = None                  
                else:
                    err = r.text[:500]
            except httpx.HTTPError as e:
                err = f"{type(e).__name__}: {e}"[:500]
            self.c.execute("INSERT INTO api_log(account_id,method,params,status,rows,error,duration_ms) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                           (self.acc["id"], "ozperf:" + base, log_params(params or {}), status, None,
                            err, int((time.time() - t0) * 1000)))
            self.c.commit()
            if data is not None:
                return data
            if status == 404 and allow_404:
                return None
            if status in (401, 429) or status is None or status >= 500:
                time.sleep(min(60, 5 * (attempt + 1) ** 2) if status != 401 else 0)
                continue
            raise OzonPerfError(f"Ozon Performance {base}: {status} {err}")
        if status == 429:
            until = datetime.now(timezone.utc) + timedelta(minutes=5)
            self.c.execute("UPDATE api_rate SET next_allowed=%s WHERE account_id=%s AND bucket=%s", (until, self.acc["id"], bucket))
            self.c.commit()
            raise RateLimited(bucket, until)
        raise OzonPerfError(f"Ozon Performance {base}: {status} {err}")
