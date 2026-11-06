"""Клиент Яндекс Маркет Partner API (api.partner.market.yandex.ru): только чтение, лимиты общие для процессов (api_rate), журнал api_log.

Ключ — Api-Key (ЛК Маркета → Настройки → API и модули), в account_tokens.enc лежит шифротекст ключа.
Многие методы чтения у Маркета — POST, поэтому «только чтение» держим белым списком (метод, шаблон пути): любой другой запрос запрещён.
"""

import json
import re
import time
from datetime import datetime, timedelta, timezone

import httpx

from .wb import RateLimited

HOST = "https://api.partner.market.yandex.ru"
READ = [
    ("GET", r"/v2/campaigns"), ("GET", r"/v2/campaigns/\d+"), ("POST", r"/v2/auth/token"),
    ("GET", r"/v2/warehouses"), ("GET", r"/v2/businesses/\d+/warehouses"),
    ("POST", r"/v2/campaigns/\d+/stats/orders"), ("POST", r"/v2/campaigns/\d+/stats/skus"),
    ("POST", r"/v2/businesses/\d+/offer-mappings"), ("POST", r"/v2/businesses/\d+/offer-prices"),
    ("POST", r"/v2/campaigns/\d+/offers/stocks"),
    
    ("POST", r"/v2/reports/(united-netting|united-marketplace-services|shows-sales|boost-consolidated|shows-boost|goods-movement|stocks-on-warehouses)/generate"),
    ("GET", r"/v2/reports/info/[\w-]+"),
]
INTERVAL = {"stats/orders": 1.0, "offer-mappings": 1.0, "offer-prices": 1.0, "offers/stocks": 1.0, "reports": 2.0}
DEFAULT_INTERVAL = 0.5

READ_SCOPES = {"ALL_METHODS_READ_ONLY", "INVENTORY_AND_ORDER_PROCESSING_READ_ONLY", "PRICING_READ_ONLY", "OFFERS_AND_CARDS_MANAGEMENT_READ_ONLY",
               "PROMOTION_READ_ONLY", "FINANCE_AND_ACCOUNTING"}


class YMError(RuntimeError):
    pass


def _allowed(method: str, path: str) -> bool:
    return any(m == method and re.fullmatch(p, path) for m, p in READ)


def _bucket(path: str) -> str:
    for k in INTERVAL:
        if k in path:
            return k
    return "other"


def check(api_key: str) -> dict:
    """Проверка ключа до сохранения магазина: доступы ключа (/v2/auth/token) и магазины кабинета (/v2/campaigns)."""
    api_key = str(api_key).strip()
    if len(api_key) < 20:
        return {"error": "Это не похоже на API-ключ Маркета (ЛК Маркета → Настройки → API и модули → «Создать новый токен»)"}
    h = {"Api-Key": api_key}
    try:
        t = httpx.post(HOST + "/v2/auth/token", headers=h, timeout=20)
        if t.status_code in (401, 403):
            return {"error": "Маркет не принял ключ: проверьте, что он скопирован целиком и не удалён в кабинете"}
        ak = ((t.json().get("result") or {}).get("apiKey") or {}) if t.status_code == 200 else {}
        scopes = ak.get("authScopes") or []
        r = httpx.get(HOST + "/v2/campaigns", headers=h, params={"limit": 50}, timeout=20)
        if r.status_code in (401, 403):
            return {"error": "Ключу не хватает прав. Нужен доступ «Все методы — только чтение» (или чтение заказов, цен, каталога и финансов)"}
        if r.status_code >= 400:
            return {"error": f"Маркет ответил {r.status_code}: {r.text[:160]}"}
        camps = r.json().get("campaigns") or []
    except httpx.HTTPError as e:
        return {"error": f"Маркет не ответил: {type(e).__name__} — попробуйте позже"}
    except ValueError:
        return {"error": "Маркет ответил не по формату — попробуйте позже"}
    if not camps:
        return {"error": "По этому ключу не видно ни одного магазина Маркета"}
    biz = {(x.get("business") or {}).get("id") for x in camps} - {None}
    if len(biz) != 1:
        return {"error": "Ключ видит несколько кабинетов Маркета — создайте ключ в нужном кабинете"}
    b = next(iter(biz))
    return {"seller_oid": int(b), "business": next((x.get("business") or {}).get("name") for x in camps), "marketplace": "ym",
            "token_name": ak.get("name"), "scopes": scopes, "read_only": bool(scopes) and all(s in READ_SCOPES for s in scopes),
            "campaigns": [{"id": x.get("id"), "domain": x.get("domain"), "placement": x.get("placementType"),
                           "api": x.get("apiAvailability")} for x in camps]}


class YM:
    def __init__(self, conn, account: dict):
        from .vault import decrypt
        self.c = conn
        self.acc = account
        row = conn.execute("SELECT enc FROM account_tokens WHERE account_id=%s", (account["id"],)).fetchone()
        if not row:
            raise SystemExit(f"у магазина {account['name']} нет ключа Маркета")
        self.business = int(account["seller_oid"])
        self.http = httpx.Client(timeout=120, headers={"Api-Key": decrypt(row["enc"]).strip()})

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
        nxt = datetime.now(timezone.utc) + timedelta(seconds=INTERVAL.get(bucket.split(":", 1)[1], DEFAULT_INTERVAL))
        self.c.execute("UPDATE api_rate SET next_allowed=%s WHERE account_id=%s AND bucket=%s", (nxt, self.acc["id"], bucket))
        self.c.commit()

    def call(self, method: str, path: str, body: dict | None = None, params: dict | None = None, max_wait: float = 120) -> dict:
        if not _allowed(method, path):
            raise YMError(f"{method} {path}: не в списке методов только для чтения — запрещено")
        bucket = "ym:" + _bucket(path)
        status, err = None, None
        for attempt in range(4):
            self._wait_slot(bucket, max_wait)
            t0 = time.time()
            err, status, data = None, None, None
            logm = f"ym:{method} " + re.sub(r"/\d+", "/{id}", path)
            try:
                r = self.http.request(method, HOST + path, json=body, params=params)
                status = r.status_code
                if status == 200:
                    data = r.json()
                else:
                    err = r.text[:500]
            except (httpx.HTTPError, ValueError) as e:
                err = f"{type(e).__name__}: {e}"[:500]
            self.c.execute("INSERT INTO api_log(account_id,method,params,status,rows,error,duration_ms) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                           (self.acc["id"], logm,
                            json.dumps({"body": body, "params": params}, ensure_ascii=False, default=str)[:2000], status, None, err,
                            int((time.time() - t0) * 1000)))
            self.c.commit()
            if data is not None:
                return data
            if status == 420 or status == 429 or status is None or status >= 500:
                time.sleep(min(60, 5 * (attempt + 1) ** 2))
                continue
            raise YMError(f"Маркет {path}: {status} {err}")
        if status in (420, 429):
            until = datetime.now(timezone.utc) + timedelta(minutes=5)
            self.c.execute("UPDATE api_rate SET next_allowed=%s WHERE account_id=%s AND bucket=%s", (until, self.acc["id"], bucket))
            self.c.commit()
            raise RateLimited(bucket, until)
        raise YMError(f"Маркет {path}: {status} {err}")

    def pages(self, method: str, path: str, body: dict | None, key, limit: int = 200):
        """Постранично по pageToken: key(result) → список элементов страницы."""
        tok = None
        while True:
            params = {"limit": limit, **({"pageToken": tok} if tok else {})}
            r = self.call(method, path, body, params)
            res = r.get("result", r)
            items = key(res) or []
            yield from items
            tok = ((res.get("paging") or {}).get("nextPageToken")) or ((r.get("paging") or {}).get("nextPageToken"))
            if not tok or not items:
                break
