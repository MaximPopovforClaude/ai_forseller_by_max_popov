"""Клиент Ozon Seller API (api-seller.ozon.ru): только чтение, лимиты общие для процессов (api_rate), журнал api_log.

Ключ магазина — пара Client-Id + Api-Key; в account_tokens.enc лежит шифротекст JSON {"client_id","api_key"}.
У Ozon все методы — POST, поэтому «только чтение» держим белым списком путей (READ_PATHS): любой другой путь запрещён.
"""

import json
import time
from datetime import datetime, timedelta, timezone

import httpx

from .wb import RateLimited
from .api_log_params import encode as log_params

HOST = "https://api-seller.ozon.ru"
READ_PATHS = {
    "/v1/review/list", "/v1/review/count", "/v1/review/comment/list",          
    "/v1/roles", "/v3/product/list", "/v3/product/info/list", "/v5/product/info/prices", "/v1/analytics/stocks",
    "/v2/analytics/stock_on_warehouses", "/v2/posting/fbo/list", "/v3/posting/fbs/list", "/v3/finance/transaction/list",
    "/v1/analytics/data", "/v1/finance/realization/by-day", "/v1/finance/products/buyout",
    "/v3/posting/fbo/list", "/v4/posting/fbs/list", "/v1/finance/accrual/by-day", "/v1/finance/accrual/types", "/v1/description-category/tree", "/v1/analytics/product-queries/details",
}
INTERVAL = {"/v1/analytics/data": 62, "/v3/finance/transaction/list": 1.5, "/v1/analytics/stocks": 1.5, "/v1/finance/products/buyout": 20,
            "/v3/posting/fbs/list": 1.5, "/v4/posting/fbs/list": 1.5, "/v3/posting/fbo/list": 1.5, "/v1/finance/accrual/by-day": 1.5, "/v1/analytics/product-queries/details": 3}
DEFAULT_INTERVAL = 0.4


class OzonError(RuntimeError):
    pass


def creds_from_blob(text: str) -> dict:
    d = json.loads(text)
    return {"client_id": str(d["client_id"]).strip(), "api_key": str(d["api_key"]).strip()}


def check(client_id: str, api_key: str) -> dict:
    """Проверка пары ключей до сохранения магазина: роли ключа (/v1/roles), иначе — пробный список товаров."""
    client_id, api_key = str(client_id).strip(), str(api_key).strip()
    if not client_id.isdigit():
        return {"error": "Client-Id — это число (ЛК Ozon → Настройки → Seller API)"}
    if len(api_key) < 20:
        return {"error": "Это не похоже на API-ключ Ozon (ЛК Ozon → Настройки → Seller API → «Сгенерировать ключ»)"}
    h = {"Client-Id": client_id, "Api-Key": api_key, "Content-Type": "application/json"}
    try:
        r = httpx.post(HOST + "/v1/roles", headers=h, json={}, timeout=20)
        if r.status_code in (401, 403):
            return {"error": "Ozon не принял ключ: проверьте Client-Id и Api-Key (ключ не отозван, Client-Id от того же кабинета)"}
        roles = []
        if r.status_code == 200:
            roles = [x.get("name") for x in (r.json().get("roles") or []) if x.get("name")]
        p = httpx.post(HOST + "/v3/product/list", headers=h, json={"filter": {"visibility": "ALL"}, "limit": 1, "last_id": ""}, timeout=20)
        if p.status_code in (401, 403):
            return {"error": "Ключу не хватает прав на товары. Нужна роль с чтением: товары, цены, остатки, отправления, финансы, аналитика "
                             "(проще всего «Admin read only»)"}
        if p.status_code >= 400:
            return {"error": f"Ozon ответил {p.status_code}: {p.text[:160]}"}
        total = (p.json().get("result") or {}).get("total")
    except httpx.HTTPError as e:
        return {"error": f"Ozon не ответил: {type(e).__name__} — попробуйте позже"}
    return {"seller_oid": int(client_id), "roles": roles, "products": total, "marketplace": "ozon",
            "read_only": bool(roles) and all("read" in (x or "").lower() for x in roles)}


class Ozon:
    def __init__(self, conn, account: dict):
        from .vault import decrypt
        self.c = conn
        self.acc = account
        row = conn.execute("SELECT enc FROM account_tokens WHERE account_id=%s", (account["id"],)).fetchone()
        if not row:
            raise SystemExit(f"у магазина {account['name']} нет ключа Ozon")
        cr = creds_from_blob(decrypt(row["enc"]))
        self.http = httpx.Client(timeout=120, headers={"Client-Id": cr["client_id"], "Api-Key": cr["api_key"],
                                                       "Content-Type": "application/json"})

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
        path = bucket.split(":", 1)[1]
        nxt = datetime.now(timezone.utc) + timedelta(seconds=INTERVAL.get(path, DEFAULT_INTERVAL))
        self.c.execute("UPDATE api_rate SET next_allowed=%s WHERE account_id=%s AND bucket=%s", (nxt, self.acc["id"], bucket))
        self.c.commit()

    def post(self, path: str, body: dict, max_wait: float = 120) -> dict:
        if path not in READ_PATHS:
            raise OzonError(f"POST {path}: не в списке методов только для чтения — запрещено")
        bucket = "ozon:" + path
        for attempt in range(4):
            self._wait_slot(bucket, max_wait)
            t0 = time.time()
            err, status, data = None, None, None
            try:
                r = self.http.post(HOST + path, json=body)
                status = r.status_code
                if status == 200:
                    data = r.json()
                else:
                    err = r.text[:500]
            except httpx.HTTPError as e:
                err = f"{type(e).__name__}: {e}"[:500]
            self.c.execute("INSERT INTO api_log(account_id,method,params,status,rows,error,duration_ms) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                           (self.acc["id"], bucket, log_params(body), status, None, err,
                            int((time.time() - t0) * 1000)))
            self.c.commit()
            if data is not None:
                return data
            if status == 429 or status is None or (status and status >= 500):
                time.sleep(min(60, 5 * (attempt + 1) ** 2))
                continue
            raise OzonError(f"Ozon {path}: {status} {err}")
        if status == 429:
            until = datetime.now(timezone.utc) + timedelta(minutes=5)
            self.c.execute("UPDATE api_rate SET next_allowed=%s WHERE account_id=%s AND bucket=%s", (until, self.acc["id"], bucket))
            self.c.commit()
            raise RateLimited(bucket, until)
        raise OzonError(f"Ozon {path}: {status} {err}")
