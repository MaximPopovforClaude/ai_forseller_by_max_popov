"""Read-only WB connectivity checks. Never return response bodies or credentials.

Run without a token: python -m stometric.wb_probe. HTTP 401/403 then confirms
network reachability only; this diagnostic cannot validate a shop key.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json

import httpx

PING = {"Статистика": "https://statistics-api.wildberries.ru/ping",
        "Контент": "https://content-api.wildberries.ru/ping",
        "Аналитика": "https://seller-analytics-api.wildberries.ru/ping",
        "Финансы": "https://finance-api.wildberries.ru/ping"}
TIMEOUT = httpx.Timeout(4.0, connect=3.0)


def check_one(item, token=None):
    name, url = item
    try:
        response = httpx.get(url, headers={"Authorization": token.strip()} if token else {},
                             timeout=TIMEOUT, follow_redirects=False)
    except httpx.TimeoutException:
        return {"section": name, "state": "unavailable", "reason": "timeout"}
    except httpx.HTTPError:
        return {"section": name, "state": "unavailable", "reason": "connection_error"}
    code = response.status_code
    if code in (401, 403):
        return {"section": name, "state": "denied", "http_status": code}
    if code == 200:
        try:
            data = response.json()
        except ValueError:
            data = None
        if isinstance(data, dict) and str(data.get("Status", data.get("status", ""))).upper() == "OK":
            return {"section": name, "state": "ok", "http_status": code}
    return {"section": name, "state": "unavailable", "reason": "rate_limit" if code == 429 else "unexpected_response",
            "http_status": code}


def checks(token=None):

    with ThreadPoolExecutor(max_workers=len(PING)) as pool:
        futures = [pool.submit(check_one, item, token) for item in PING.items()]
        return [f.result() for f in futures]


def verify(token):
    rows = checks(token)
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "checks": rows, "warnings": []}
    denied = [r for r in rows if r["state"] == "denied"]
    if denied:
        sections = ", ".join(f"{r['section']}: {r['http_status']}" for r in denied)
        result.update(error=f"WB отказал в доступе ({sections}). Проверьте срок и права ключа, а также доступ к WB с вашего сервера.", error_status=400)
        return result
    unavailable = [r for r in rows if r["state"] == "unavailable"]
    if not any(r["state"] == "ok" for r in rows):
        result.update(error="Не удалось подтвердить ключ ни в одном разделе WB: сеть, лимит или временный сбой API. "
                            "Новый ключ не сохранён. Повторите позже; на своём сервере проверьте доступность API WB.", error_status=503)
    elif unavailable:
        names = ", ".join(r["section"] for r in unavailable)
        result["warnings"] = [f"Ключ подтверждён WB, но при подключении не удалось проверить разделы: {names}. "
                              "Их данные могут появиться позже. Проверьте «Статус обновления»; если сбой сохраняется, проверьте доступ к API WB с сервера."]
    return result


if __name__ == "__main__":

    print(json.dumps({"authenticated": False, "checks": checks(),
                      "note": "Без ключа: HTTP 401/403 означает, что HTTP-ответ получен, но не подтверждает доступ магазина. "
                              "timeout/connection_error — проверьте DNS, исходящий HTTPS, прокси и доступность WB."}, ensure_ascii=False, indent=2))
