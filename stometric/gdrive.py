"""Self-hosted application component."""

import json
import time

import httpx

from . import vault
from .legal import SITE

KEY = "google_drive"
SCOPE = "https://www.googleapis.com/auth/drive.file openid email"
REDIRECT = f"{SITE}/api/admin/google/callback"
FOLDER = "seller-analytics — выгрузки"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_tok: dict = {}          


class GError(Exception):
    pass


def _get(c) -> dict:
    r = c.execute("SELECT value FROM app_settings WHERE key=%s", (KEY,)).fetchone()
    return (r and r["value"]) or {}


def _secret(c) -> dict:
    v = _get(c)
    return json.loads(vault.decrypt(v["enc"].encode())) if v.get("enc") else {}


def _save(c, sec: dict, **pub) -> None:
    v = {k: x for k, x in _get(c).items() if k != "enc"}
    v.update(pub)
    v["enc"] = vault.encrypt(json.dumps(sec)).decode()
    c.execute("INSERT INTO app_settings(key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", (KEY, json.dumps(v)))


def status(c) -> dict:
    v, s = _get(c), _secret(c)
    return {"client": bool(s.get("client_id")), "connected": bool(s.get("refresh_token")), "email": v.get("email"),
            "folder_url": f"https://drive.google.com/drive/folders/{v['folder_id']}" if v.get("folder_id") else None,
            "redirect": REDIRECT}


def ready(c) -> bool:
    return bool(_secret(c).get("refresh_token") and _get(c).get("folder_id"))


def set_client(c, client_id: str, client_secret: str) -> None:
    client_id, client_secret = client_id.strip(), client_secret.strip()
    if not client_id.endswith(".apps.googleusercontent.com"):
        raise GError("Client ID должен заканчиваться на .apps.googleusercontent.com")
    if len(client_secret) < 10:
        raise GError("Не похоже на Client secret")
    _tok.clear()
    _save(c, {"client_id": client_id, "client_secret": client_secret}, email=None, folder_id=None)


def auth_url(c, uid: int) -> str:
    s = _secret(c)
    if not s.get("client_id"):
        raise GError("Сначала сохраните Client ID и Client secret")
    state = vault.encrypt(json.dumps({"uid": uid, "ts": int(time.time())})).decode()
    q = httpx.QueryParams({"client_id": s["client_id"], "redirect_uri": REDIRECT, "response_type": "code", "scope": SCOPE,
                           "access_type": "offline", "prompt": "consent", "state": state})
    return f"https://accounts.google.com/o/oauth2/v2/auth?{q}"


def check_state(state: str) -> int:
    try:
        d = json.loads(vault.decrypt(state.encode()))
    except Exception:  
        raise GError("Ссылка подключения недействительна — начните заново в админке") from None
    if time.time() - d["ts"] > 900:
        raise GError("Ссылка подключения устарела — начните заново в админке")
    return d["uid"]


def finish(c, code: str) -> str:
    """Код из Google → токен обновления, почта аккаунта, папка для выгрузок. Возвращает почту."""
    s = _secret(c)
    r = httpx.post("https://oauth2.googleapis.com/token", timeout=30, data={
        "code": code, "client_id": s["client_id"], "client_secret": s["client_secret"], "redirect_uri": REDIRECT, "grant_type": "authorization_code"})
    d = r.json()
    if r.status_code != 200 or not d.get("refresh_token"):
        raise GError(f"Google не выдал доступ: {d.get('error_description') or d.get('error') or r.status_code}")
    s["refresh_token"] = d["refresh_token"]
    _tok.update(v=d["access_token"], exp=time.time() + int(d.get("expires_in", 3600)) - 120)
    h = {"Authorization": f"Bearer {d['access_token']}"}
    email = httpx.get("https://openidconnect.googleapis.com/v1/userinfo", headers=h, timeout=30).json().get("email")
    folder = _get(c).get("folder_id")
    if not folder:
        f = httpx.post("https://www.googleapis.com/drive/v3/files?fields=id", headers=h, timeout=30,
                       json={"name": FOLDER, "mimeType": "application/vnd.google-apps.folder"})
        if f.status_code != 200:
            raise GError(f"Не удалось создать папку на Диске: {f.status_code}")
        folder = f.json()["id"]
    _save(c, s, email=email, folder_id=folder)
    return email


def _access(c) -> str:
    if _tok.get("v") and _tok.get("exp", 0) > time.time():
        return _tok["v"]
    s = _secret(c)
    if not s.get("refresh_token"):
        raise GError("Google Диск не подключён — владелец сервиса подключает его в админке")
    r = httpx.post("https://oauth2.googleapis.com/token", timeout=30, data={
        "client_id": s["client_id"], "client_secret": s["client_secret"], "refresh_token": s["refresh_token"], "grant_type": "refresh_token"})
    d = r.json()
    if r.status_code != 200:
        raise GError("Google отозвал доступ — переподключите Google Диск в админке" if d.get("error") == "invalid_grant"
                     else f"Google не ответил: {d.get('error') or r.status_code}")
    _tok.update(v=d["access_token"], exp=time.time() + int(d.get("expires_in", 3600)) - 120)
    return _tok["v"]


def upload(c, body: bytes, name: str, share_to: str | None) -> dict:
    """xlsx → новая Google Таблица в папке выгрузок; доступ «редактор» — на почту пользователя. {"url", "shared", "note"}."""
    v = _get(c)
    h = {"Authorization": f"Bearer {_access(c)}"}
    meta = {"name": name, "mimeType": "application/vnd.google-apps.spreadsheet", "parents": [v["folder_id"]]}
    r = httpx.post("https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,webViewLink", headers=h, timeout=120,
                   files={"metadata": (None, json.dumps(meta), "application/json; charset=UTF-8"), "file": ("t.xlsx", body, XLSX)})
    if r.status_code == 404:
        raise GError("Папка выгрузок на Google Диске не найдена — переподключите Google Диск в админке")
    if r.status_code != 200:
        raise GError(f"Google не принял таблицу: {r.status_code} {r.text[:200]}")
    f = r.json()
    out = {"url": f["webViewLink"], "shared": False, "note": None}
    if not share_to or share_to.lower() == (v.get("email") or "").lower():
        out["shared"] = True
        return out
    perm = {"type": "user", "role": "writer", "emailAddress": share_to}
    url = f"https://www.googleapis.com/drive/v3/files/{f['id']}/permissions"
    p = httpx.post(url, params={"sendNotificationEmail": "false"}, headers=h, json=perm, timeout=30)
    if p.status_code != 200:            
        p = httpx.post(url, params={"sendNotificationEmail": "true", "emailMessage": "Выгрузка из platform.example.org"}, headers=h, json=perm, timeout=30)
    if p.status_code == 200:
        out["shared"] = True
    else:
        out["note"] = f"Не удалось открыть доступ для {share_to}: к этой почте не привязан Google-аккаунт. Войдите в Google под почтой с аккаунтом и попросите владельца открыть доступ."
    return out
