"""Пароли (scrypt), сессии и проверка прав. В базе — только хеши паролей и токенов сессий/приглашений."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

SESSION_DAYS = 30
ROLE_RANK = {"viewer": 1, "editor": 2, "admin": 3, "owner": 4}


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_password(pw: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        hashlib.scrypt(pw.encode(), salt=b"0" * 16, n=2 ** 14, r=8, p=1, dklen=32)    
        return False
    _, salt, h = stored.split("$")
    got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32)
    return hmac.compare_digest(got.hex(), h)


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session(c, user_id: int, ip: str | None, ua: str | None) -> str:
    tok = secrets.token_urlsafe(32)
    c.execute("INSERT INTO sessions(token_hash,user_id,expires_at,ip,user_agent) VALUES (%s,%s,%s,%s,%s)",
              (_h(tok), user_id, datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS), ip, (ua or "")[:300]))
    c.execute("UPDATE users SET last_login_at=now() WHERE id=%s", (user_id,))
    c.commit()
    return tok


def session_user(c, tok: str | None) -> dict | None:
    if not tok:
        return None
    return c.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=%s AND s.expires_at>now() AND u.is_active",
        (_h(tok),)).fetchone()


def drop_session(c, tok: str) -> None:
    c.execute("DELETE FROM sessions WHERE token_hash=%s", (_h(tok),))
    c.commit()


from datetime import timedelta as _td, timezone as _tz
MSK = _tz(_td(hours=3))


def _support(c, user: dict) -> list[dict]:
    """Self-hosted application component."""
    if not user.get("is_superadmin"):
        return []
    return c.execute("""SELECT workspace_id, max(until) until FROM support_access WHERE user_id=%s AND revoked_at IS NULL AND until > now()
                        GROUP BY 1""", (user["id"],)).fetchall()


def shops_for(c, user: dict) -> list[dict]:
    """Магазины, которые видит пользователь, с его ролью. Суперадмин — как все: только свои кабинеты; чужой — только по открытому
    доступу поддержки (роль «просмотр», пометка в названии кабинета)."""
    if not user or user.get("is_active") is False:
        return []
    own = c.execute(
        """SELECT a.id,a.name,a.title,a.marketplace,a.workspace_id,w.name workspace,m.role FROM memberships m
           JOIN workspaces w ON w.id=m.workspace_id JOIN accounts a ON a.workspace_id=m.workspace_id
           WHERE m.user_id=%s AND a.is_active AND (m.shop_ids IS NULL OR a.id = ANY(m.shop_ids))
           ORDER BY w.name,a.title""", (user["id"],)).fetchall()
    g = user.get("_mcp")
    if g:                                  
        return [o for o in own if o["workspace_id"] == g["workspace_id"] and (g.get("shops") is None or o["id"] in g["shops"])]
    sup = [x for x in _support(c, user) if x["workspace_id"] not in {o["workspace_id"] for o in own}]
    if sup:
        until = {x["workspace_id"]: x["until"] for x in sup}
        for r in c.execute("""SELECT a.id,a.name,a.title,a.marketplace,a.workspace_id,w.name workspace,'viewer' AS role FROM accounts a
                              JOIN workspaces w ON w.id=a.workspace_id WHERE a.is_active AND a.workspace_id = ANY(%s) ORDER BY w.name,a.title""",
                           (list(until),)).fetchall():
            r["workspace"] = f"{r['workspace']} · поддержка до {until[r['workspace_id']].astimezone(MSK):%H:%M}"
            r["support"] = True
            own.append(r)
    return own


def workspaces_for(c, user: dict) -> list[dict]:
    """Кабинеты пользователя с его ролью; суперадмин — свои и открытые доступом поддержки (только просмотр)."""
    if not user or user.get("is_active") is False:
        return []
    own = c.execute("SELECT w.id,w.name,w.plan,m.role FROM memberships m JOIN workspaces w ON w.id=m.workspace_id "
                    "WHERE m.user_id=%s ORDER BY w.id", (user["id"],)).fetchall()
    if user.get("_mcp"):
        return [w for w in own if w["id"] == user["_mcp"]["workspace_id"]]
    sup = [x["workspace_id"] for x in _support(c, user) if x["workspace_id"] not in {o["id"] for o in own}]
    if sup:
        own += c.execute("SELECT id,name,plan,'viewer' AS role, true AS support FROM workspaces WHERE id = ANY(%s) ORDER BY id", (sup,)).fetchall()
    return own


def workspace_role(c, user: dict, ws_id: int) -> str | None:
    return next((w["role"] for w in workspaces_for(c, user) if w["id"] == ws_id), None)


def shop_role(c, user: dict, shop_id: int) -> str | None:
    for s in shops_for(c, user):
        if s["id"] == shop_id:
            return s["role"]
    return None


def can(role: str | None, need: str) -> bool:
    return role is not None and ROLE_RANK[role] >= ROLE_RANK[need]
