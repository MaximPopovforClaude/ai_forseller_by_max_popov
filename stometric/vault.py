"""Self-hosted application component."""

import base64
import json
from datetime import datetime, timezone

from cryptography.fernet import Fernet

from . import config
from .wb_probe import PING, verify

MASTER = "AIS_MASTER_KEY"

SCOPES = {1: "Контент", 2: "Аналитика", 3: "Цены и скидки", 4: "Маркетплейс", 5: "Статистика", 6: "Продвижение",
          7: "Вопросы и отзывы", 9: "Чат с покупателями", 10: "Поставки", 11: "Возвраты покупателями", 12: "Документы",
          13: "Финансы", 16: "Пользователи", 30: "Только чтение"}
NEED = ["Контент", "Аналитика", "Цены и скидки", "Статистика", "Продвижение", "Финансы"]   


def _fernet() -> Fernet:
    return Fernet(config.get(MASTER).encode())


def encrypt(token: str) -> bytes:
    return _fernet().encrypt(token.encode())


def decrypt(blob: bytes) -> str:
    return _fernet().decrypt(bytes(blob)).decode()


def info(token: str) -> dict:
    """Что видно из самого ключа WB (JWT) без сети. Ошибки — понятным текстом в "error"."""
    token = token.strip()
    try:
        p = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    except Exception:  
        return {"error": "Это не похоже на ключ API Wildberries (Личный кабинет → Настройки → Доступ к API)"}
    s = int(p.get("s") or 0)
    scopes = [n for b, n in SCOPES.items() if s >> b & 1]
    exp = datetime.fromtimestamp(p["exp"], timezone.utc) if p.get("exp") else None
    out = {"seller_oid": p.get("oid"), "exp": exp, "scopes": scopes, "test": bool(p.get("t")), "read_only": "Только чтение" in scopes,
           "kind": {"self": "Персональный", "service": "Сервисный"}.get(p.get("for"), p.get("for") or "—")}
    if out["test"]:
        out["error"] = "Это ключ тестового контура WB — нужен боевой"
    elif exp and exp < datetime.now(timezone.utc):
        out["error"] = f"Срок ключа истёк {exp:%d.%m.%Y}"
    elif missing := [n for n in NEED if n not in scopes]:
        out["error"] = "В ключе не хватает разделов: " + ", ".join(missing)
    return out


def ping(token: str) -> str | None:
    """Compatibility wrapper; callers needing partial-result warnings use verify."""
    return verify(token).get("error")


def token_for(c, account: dict) -> str:
    row = c.execute("SELECT enc FROM account_tokens WHERE account_id=%s", (account["id"],)).fetchone()
    if row:
        return decrypt(row["enc"])
    if not account.get("token_env"):
        raise SystemExit(f"у магазина {account['name']} нет ключа API")
    return config.get(account["token_env"])
