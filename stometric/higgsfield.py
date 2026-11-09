"""Self-hosted application component."""

import base64
import hashlib
import json
import secrets
import time
import urllib.parse

import httpx

AUTH = "https://clerk.higgsfield.ai/oauth"
MCP = "https://mcp.higgsfield.ai/mcp"
from .config import site_url
REDIRECT = site_url() + "/api/higgsfield/callback"
SCOPE = "openid email offline_access"


MODELS = {
    "nano_pro": {"title": "Nano Banana Pro", "model": "nano_banana_pro", "params": {"resolution": "2k"}},
    "nano2": {"title": "Nano Banana 2", "model": "nano_banana_2", "params": {"resolution": "2k"}},
    "gpt": {"title": "GPT Image 2.5", "model": "gpt_image_2_5", "params": {"variant": "flare", "quality": "high", "resolution": "2k"}},
    "sunburst": {"title": "GPT Image 2.5 Sunburst", "model": "gpt_image_2_5", "params": {"variant": "sunburst", "quality": "high", "resolution": "2k"}},
    "seedream": {"title": "Seedream 5.0 Pro", "model": "seedream_v5_pro", "params": {"resolution": "2k"}},
}


class HFError(RuntimeError):
    pass


def _j(v):
    return v if isinstance(v, dict) else json.loads(v)



def _client_id(c) -> str:
    r = c.execute("SELECT value FROM app_settings WHERE key='hf_oauth_client'").fetchone()
    if r:
        return _j(r["value"])["client_id"]
    d = httpx.post(f"{AUTH}/register", json={"client_name": "platform.example.org AI-100metric", "redirect_uris": [REDIRECT],
                                               "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
                                               "token_endpoint_auth_method": "none", "scope": SCOPE}, timeout=30).json()
    c.execute("INSERT INTO app_settings(key,value) VALUES ('hf_oauth_client',%s)", (json.dumps({"client_id": d["client_id"]}),))
    return d["client_id"]


def auth_url(c, ws_id: int, uid: int) -> str:
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    c.execute("INSERT INTO app_settings(key,value) VALUES (%s,%s)",
              (f"hf_oauth_state:{state}", json.dumps({"ws": ws_id, "uid": uid, "v": verifier, "at": time.time()})))
    return f"{AUTH}/authorize?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": _client_id(c), "redirect_uri": REDIRECT, "scope": SCOPE, "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256", "resource": MCP})


def _save(c, ws_id: int, uid: int | None, tok: dict, email: str | None = None):
    from . import vault
    blob = json.dumps({"access": tok["access_token"], "refresh": tok.get("refresh_token"), "exp": time.time() + int(tok.get("expires_in") or 3600) - 60})
    c.execute("""INSERT INTO workspace_secrets(workspace_id,kind,enc,info,added_by) VALUES (%s,'higgsfield',%s,%s,%s) ON CONFLICT (workspace_id,kind)
                 DO UPDATE SET enc=EXCLUDED.enc, info=CASE WHEN %s THEN EXCLUDED.info ELSE workspace_secrets.info END,
                 added_by=coalesce(EXCLUDED.added_by, workspace_secrets.added_by)""",
              (ws_id, vault.encrypt(blob), json.dumps({"email": email} if email else {}), uid, bool(email)))


def callback(c, state: str, code: str) -> int:
    r = c.execute("DELETE FROM app_settings WHERE key=%s RETURNING value", (f"hf_oauth_state:{state}",)).fetchone()
    if not r:
        raise HFError("Ссылка входа устарела — нажмите «Подключить» ещё раз")
    st = _j(r["value"])
    if time.time() - st["at"] > 1800:
        raise HFError("Ссылка входа устарела — нажмите «Подключить» ещё раз")
    t = httpx.post(f"{AUTH}/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
                                          "client_id": _client_id(c), "code_verifier": st["v"]}, timeout=30)
    if t.status_code != 200:
        raise HFError(f"Higgsfield не выдал доступ ({t.status_code})")
    tok = t.json()
    email = None
    try:
        payload = tok.get("id_token", "").split(".")[1]
        email = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("email")
    except Exception:  
        pass
    _save(c, st["ws"], st["uid"], tok, email)
    return st["ws"]


def _token(c, ws_id: int) -> str | None:
    from . import vault
    r = c.execute("SELECT enc FROM workspace_secrets WHERE workspace_id=%s AND kind='higgsfield'", (ws_id,)).fetchone()
    if not r:
        return None
    d = json.loads(vault.decrypt(bytes(r["enc"])))
    c.commit()                  
    if d["exp"] > time.time():
        return d["access"]
    if not d.get("refresh"):
        raise HFError("Вход в Higgsfield истёк — подключите аккаунт заново (Настройки аккаунта)")
    t = httpx.post(f"{AUTH}/token", data={"grant_type": "refresh_token", "refresh_token": d["refresh"], "client_id": _client_id(c)}, timeout=30)
    if t.status_code != 200:
        raise HFError("Вход в Higgsfield истёк — подключите аккаунт заново (Настройки аккаунта)")
    tok = t.json()
    tok.setdefault("refresh_token", d["refresh"])
    _save(c, ws_id, None, tok)
    c.commit()
    return tok["access_token"]


def shop_ws(c, shop: int) -> int:
    return c.execute("SELECT workspace_id FROM accounts WHERE id=%s", (shop,)).fetchone()["workspace_id"]


def connected(c, shop: int) -> bool:
    return bool(c.execute("SELECT 1 FROM workspace_secrets WHERE workspace_id=%s AND kind='higgsfield'", (shop_ws(c, shop),)).fetchone())



class Client:
    def __init__(self, c, shop: int):
        tok = _token(c, shop_ws(c, shop))
        if not tok:
            raise HFError("Аккаунт Higgsfield не подключён — Настройки аккаунта → «Higgsfield»")
        self.h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "Authorization": f"Bearer {tok}"}
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "ai-stometric", "version": "1.0"}})
        self._rpc("notifications/initialized", {}, notify=True)

    def _rpc(self, method: str, params: dict, notify: bool = False) -> dict:
        body = {"jsonrpc": "2.0", "method": method, "params": params, **({} if notify else {"id": 1})}
        r = httpx.post(MCP, headers=self.h, json=body, timeout=120)
        if r.status_code == 401:
            raise HFError("Вход в Higgsfield истёк — подключите аккаунт заново (Настройки аккаунта)")
        if r.status_code >= 400:
            raise HFError(f"Higgsfield ответил {r.status_code}")
        if r.headers.get("mcp-session-id"):
            self.h["Mcp-Session-Id"] = r.headers["mcp-session-id"]
        if notify:
            return {}
        chunks = [ln[6:] for ln in r.text.split("\n") if ln.startswith("data: ")]
        return json.loads(chunks[-1]) if chunks else (r.json() if r.text.strip() else {})

    def call(self, tool: str, **args) -> dict:
        resp = self._rpc("tools/call", {"name": tool, "arguments": args})
        if "error" in resp:
            raise HFError(str(resp["error"].get("message"))[:300])
        res = resp.get("result") or {}
        if res.get("structuredContent"):
            out = res["structuredContent"]
        else:
            text = "".join(x.get("text", "") for x in res.get("content") or [] if x.get("type") == "text")
            try:
                out = json.loads(text)
            except ValueError:
                out = {"text": text}
        if res.get("isError"):
            raise HFError(str(out.get("error") or out.get("text") or out)[:300])
        return out


def _params(model: str, prompt: str, media_ids: list[str]) -> dict:
    m = MODELS[model]
    p = {"model": m["model"], "prompt": prompt[:5000], "aspect_ratio": "3:4", **m["params"], "use_unlim": False}
    if media_ids:
        p["medias"] = [{"role": "image_references", "value": x} for x in media_ids[:10]]
    return p


def cost(cl: Client, model: str) -> float | None:
    try:
        r = cl.call("generate_image", params={**_params(model, "product slide", []), "get_cost": True},
                    context="Cost preflight for marketplace card slides")
        return float((r.get("cost") or {}).get("credits_exact") or (r.get("cost") or {}).get("credits"))
    except (HFError, TypeError, ValueError):
        return None


def upload(cl: Client, raw: bytes, mime: str, name: str) -> str:
    r = cl.call("media_upload", filename=name, content_type=mime)
    u = (r.get("uploads") or [r])[0]
    p = httpx.put(u["upload_url"], content=raw, headers={"Content-Type": mime}, timeout=120)
    if p.status_code >= 300:
        raise HFError(f"Higgsfield не принял фото-образец ({p.status_code})")
    cl.call("media_confirm", media_id=u["media_id"], type="image")
    return u["media_id"]


def submit(cl: Client, model: str, prompt: str, media_ids: list[str]) -> str:
    r = cl.call("generate_image_batch", requests=[{"index": 0, "params": _params(model, prompt, media_ids)}],
                context="Marketplace product card slides by an approved brief")
    jobs = r.get("jobs") or []
    if not jobs or not jobs[0].get("job_id"):
        raise HFError(f"Higgsfield не принял задачу: {str(r.get('errors') or r.get('failed') or r)[:300]}")
    return jobs[0]["job_id"]


def wait(cl: Client, job_id: str) -> dict:
    r = cl.call("jobs_wait", jobs=[{"index": 0, "job_id": job_id}], timeout_seconds=15)
    return (r.get("jobs") or [{}])[0]
