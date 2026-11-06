"""Клиент API WB: только чтение, лимиты общие для всех процессов (таблица api_rate), архив сырых ответов, журнал api_log.

Лимиты — для Персонального токена (knowledge/wb_api_methods.md); ответ 429 сдвигает окно по заголовку X-Ratelimit-Retry
(у Базового токена это может быть 3 часа) — тогда бросаем RateLimited, а не спим: сборщик продолжит в следующий запуск.
"""

import gzip
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from . import config

HOSTS = {
    "statistics": "https://statistics-api.wildberries.ru",
    "analytics": "https://seller-analytics-api.wildberries.ru",
    "content": "https://content-api.wildberries.ru",
    "prices": "https://discounts-prices-api.wildberries.ru",
    "advert": "https://advert-api.wildberries.ru",
    "finance": "https://finance-api.wildberries.ru",
    "marketplace": "https://marketplace-api.wildberries.ru",
    "supplies": "https://supplies-api.wildberries.ru",
    "common": "https://common-api.wildberries.ru",
    "documents": "https://documents-api.wildberries.ru",
    "feedbacks": "https://feedbacks-api.wildberries.ru",
    "calendar": "https://dp-calendar-api.wildberries.ru",     
}


INTERVAL = {
    "statistics:/api/v1/supplier/orders": 62,
    "statistics:/api/v1/supplier/sales": 62,
    "finance:/api/finance/v1/sales-reports/detailed": 62,
    "finance:/api/finance/v1/acquiring/detailed": 62,
    "analytics:/api/analytics/v3/sales-funnel/products/history": 21,
    "analytics:/api/analytics/v3/sales-funnel/products": 21,
    "analytics:/api/analytics/v1/stocks-report/wb-warehouses": 21,
    "analytics:/api/analytics/v1/stocks-report/seller-warehouses": 21,
    "analytics:/api/analytics/v1/order-feed": 62,
    "analytics:/api/v1/paid_storage": 62,
    "analytics:/api/v1/paid_storage/tasks/status": 6,
    "analytics:/api/v1/paid_storage/tasks/download": 62,
    "analytics:/api/v1/acceptance_report": 62,
    "analytics:/api/v1/acceptance_report/tasks/status": 6,
    "analytics:/api/v1/acceptance_report/tasks/download": 62,
    "common:/api/v1/seller-info": 2,
    "analytics:/api/v1/warehouse_remains": 62,
    "analytics:/api/v2/stocks-report/products/products": 21,
    "analytics:/api/v2/stocks-report/offices": 21,
    "analytics:/api/v1/warehouse_remains/tasks/status": 6,
    "analytics:/api/v1/warehouse_remains/tasks/download": 62,
    "calendar:/api/v1/calendar/promotions": 0.7,
    "calendar:/api/v1/calendar/promotions/details": 0.7,
    "calendar:/api/v1/calendar/promotions/nomenclatures": 0.7,
    "advert:/adv/v3/fullstats": 21,
    "advert:/adv/v1/upd": 1.2,
    "advert:/api/advert/v2/adverts": 0.3,
    "advert:/adv/v1/promotion/count": 0.3,
    "advert:/adv/v1/normquery/stats": 6.5,
    "advert:/adv/v0/normquery/list": 0.3,
    "advert:/adv/v0/normquery/get-minus": 0.3,
    "advert:/adv/v0/normquery/get-bids": 0.3,
    "advert:/api/advert/v0/bids/recommendations": 12.5,     
    "advert:/api/advert/v2/budget": 3.1,                    
    "advert:/adv/v1/balance": 1.1,
    "content:/content/v2/get/cards/list": 0.7,
    "prices:/api/v2/list/goods/filter": 0.7,
    "common:/api/v1/tariffs/commission": 62,
    "supplies:/api/v1/supplies": 2.2,
    "marketplace:/api/v3/warehouses": 0.3,
    "feedbacks:/api/v1/feedbacks": 0.4,
    "content:/content/v2/object/charcs": 0.7,
    "content:/content/v2/cards/error/list": 6.5,
    "feedbacks:/api/v1/feedbacks/archive": 0.4,
    "feedbacks:/api/v1/feedback": 0.4,
    "feedbacks:/api/v1/feedbacks/answer": 0.4,
    "feedbacks:/api/v1/questions": 0.4,
}
DEFAULT_INTERVAL = 21


WRITE_PATTERNS = re.compile(r"/(save-ad|delete|rename|start|pause|stop|deposit|upload|bids(?!/min|/recommendations)|set-minus|"
                            r"drafts|cancel|update|create)\b", re.I)
READ_POSTS = {"/content/v2/get/cards/list", "/api/analytics/v3/sales-funnel/products/history",
              "/api/analytics/v3/sales-funnel/products", "/api/analytics/v1/stocks-report/wb-warehouses",
              "/api/analytics/v1/stocks-report/seller-warehouses", "/api/analytics/v1/order-feed",
              "/api/finance/v1/sales-reports/detailed", "/api/finance/v1/sales-reports/list",
              "/api/finance/v1/acquiring/detailed", "/api/v1/supplies", "/adv/v1/normquery/stats", "/api/advert/v2/budget",
              "/api/v2/search-report/product/search-texts", "/api/v2/list/goods/filter",
              "/api/v2/stocks-report/products/products", "/api/v2/stocks-report/offices"}  
READ_POSTS.add("/api/analytics/v3/sales-funnel/products")
READ_POSTS.add("/content/v2/cards/error/list")   
READ_POSTS.add("/api/analytics/v2/item-rating")   
READ_POSTS |= {"/adv/v0/normquery/get-bids", "/adv/v0/normquery/get-minus", "/adv/v0/normquery/list"}   


class WBError(RuntimeError):
    pass


class RateLimited(WBError):
    def __init__(self, bucket: str, until: datetime):
        super().__init__(f"лимит WB по {bucket}: следующий вызов после {until:%d.%m %H:%M:%S} UTC")
        self.until = until


def _bucket(host: str, path: str) -> str:
    p = re.sub(r"/tasks/[^/]+/(status|download)$", r"/tasks/\1", path)
    return f"{host}:{p}"


class WB:
    def __init__(self, conn, account: dict):
        self.c = conn
        self.acc = account
        from .vault import token_for
        self.token = token_for(conn, account)
        self.http = httpx.Client(timeout=300, headers={"Authorization": self.token})

    
    def _wait_slot(self, bucket: str, max_wait: float = 120):
        row = self.c.execute(
            "INSERT INTO api_rate(account_id,bucket,next_allowed) VALUES (%s,%s,now()) "
            "ON CONFLICT (account_id,bucket) DO UPDATE SET bucket=EXCLUDED.bucket RETURNING next_allowed,blocked_until",
            (self.acc["id"], bucket)).fetchone()
        
        
        now = datetime.now(timezone.utc)
        reserved = max(now, row["next_allowed"], row.get("blocked_until") or now)
        wait = (reserved - now).total_seconds()
        if wait > max_wait:
            self.c.commit()  
            raise RateLimited(bucket, reserved)
        nxt = reserved + timedelta(seconds=INTERVAL.get(bucket, DEFAULT_INTERVAL))
        self.c.execute("UPDATE api_rate SET next_allowed=%s WHERE account_id=%s AND bucket=%s", (nxt, self.acc["id"], bucket))
        self.c.commit()
        remaining = (reserved - datetime.now(timezone.utc)).total_seconds()
        if remaining > 0:
            time.sleep(remaining)
        
        
        penalty = self.c.execute("SELECT blocked_until FROM api_rate WHERE account_id=%s AND bucket=%s",
                                 (self.acc["id"], bucket)).fetchone()
        self.c.commit()
        if penalty and penalty.get("blocked_until") and penalty["blocked_until"] > datetime.now(timezone.utc):
            raise RateLimited(bucket, penalty["blocked_until"])

    def _penalty(self, bucket: str, seconds: float) -> datetime:
        until = datetime.now(timezone.utc) + timedelta(seconds=seconds + 2)
        row = self.c.execute("UPDATE api_rate SET next_allowed=GREATEST(next_allowed,%s), blocked_until=GREATEST(blocked_until,%s) WHERE account_id=%s AND bucket=%s RETURNING blocked_until",
                             (until, until, self.acc["id"], bucket)).fetchone()
        self.c.commit()
        return row["blocked_until"] if row else until

    
    def _archive(self, bucket: str, payload) -> str:
        now = datetime.now(timezone.utc)
        slug = re.sub(r"[^a-z0-9]+", "_", bucket.lower()).strip("_")
        d = config.RAW_ARCHIVE / self.acc["name"] / slug / now.strftime("%Y-%m-%d")
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{now:%H%M%S_%f}.json.gz"
        with gzip.open(f, "wt", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        return str(f.relative_to(config.ROOT))

    
    def call(self, host: str, path: str, method: str = "GET", params: dict | None = None, body=None,
             bucket_path: str | None = None, max_wait: float = 120, raw: bool = False):
        if WRITE_PATTERNS.search(path) or (method == "POST" and path not in READ_POSTS):
            raise WBError(f"{method} {path}: не в списке методов только для чтения — запрещено")
        bucket = _bucket(host, bucket_path or path)
        self._wait_slot(bucket, max_wait)
        url = HOSTS[host] + path
        t0 = time.monotonic()
        status, rows, arch, err, data = None, None, None, None, None
        try:
            r = self.http.request(method, url, params=params, json=body)
            status = r.status_code
            if status == 429:
                retry = float(r.headers.get("X-Ratelimit-Retry") or r.headers.get("Retry-After") or 60)
                raise RateLimited(bucket, self._penalty(bucket, retry))
            if status >= 400:
                err = r.text[:500]
                raise WBError(f"{method} {path}: HTTP {status}: {err}")
            data = r.content if raw else (r.json() if r.content.strip() else None)
            if not raw:
                arch = self._archive(bucket, {"request": {"method": method, "path": path, "params": params, "body": body},
                                              "fetched_at": datetime.now(timezone.utc).isoformat(), "response": data})
                rows = len(data) if isinstance(data, list) else None
            return data
        except RateLimited as e:
            err = str(e)
            raise
        except httpx.HTTPError as e:
            err = f"{type(e).__name__}: {e}"
            raise WBError(err) from None
        finally:
            self.c.execute(
                "INSERT INTO api_log(account_id,method,params,status,rows,archive,error,duration_ms) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (self.acc["id"], f"{method} {host}{path}", json.dumps({"params": params, "body": body}, ensure_ascii=False, default=str),
                 status, rows, arch, err, int((time.monotonic() - t0) * 1000)))
            self.c.commit()
