"""Self-hosted application component."""

import hashlib
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

LEVELS = {"read": "Только чтение", "platform": "Чтение + изменения в платформе",
          "market": "Чтение + изменения в платформе и в кабинете маркетплейса"}
PLANS = ("ai", "mcp", "owner")
PREFIX = "mcp_"
RATE_MIN = 120               
TOKEN_DAYS = 90

_SHOP = r"^/api/shops/\d+/"
BLOCKS = {                   
    "platform:kb": ("База знаний", [r"^/api/(workspaces/\d+/kb|kb)/"]),
    "platform:costs": ("Себестоимость и доп. расходы", [_SHOP + r"(cost|cost/import|cost/import_url|ext_costs(/\d+)?|cost/drafts/\d+/apply)$"]),
    "platform:analytics": ("Планы, юнит-экономика, налог, исключения, акции, чек-листы, гипотезы, действия по артикулам, выгрузки",
                           [_SHOP + r"(nm_plan|plan/[a-z_]+|unit_extra|tax|exclusions(/batch)?|promo/[a-z]+|checklist|checklist_max/\d+|"
                                    r"hypotheses(/\d+)?|actions(/\d+)?|manager/other_pct|manager/prices/\d+|prefs/[\w-]+|"
                                    r"photo_funnel/\d+/snap|entry_points(/\d+)?|ai_report/build|tab/[\w-]+/gsheet)$"]),
    "platform:groups": ("Группы товаров, менеджеры, конкуренты",
                        [_SHOP + r"(group|competitors/\d+(/\d+)?|staff/assign)$", r"^/api/workspaces/\d+/staff(/import)?$", r"^/api/staff/\d+$"]),
    "platform:seo": ("SEO: сбор, тексты, отправка на согласование", [_SHOP + r"seo(/\d+(/[a-z]+)?|_rules|_review/\d+/return)$"]),
    "platform:visual": ("Визуал: проекты, ТЗ, отрисовка (тратит генерации)", [_SHOP + r"visual(_brand|_photo/\d+|_brief/\d+/apply)?(/.*)?$"]),
    "platform:cards": ("Карточки: черновики правок", [_SHOP + r"cards/(rules|\d+/(ai|draft|rebase|from_visual|upload))$"]),
    "platform:reviews": ("Отзывы и вопросы: черновики ответов, правила, рекомендации",
                         [_SHOP + r"(reviews|questions)/(\d+/draft|answers/\d+/comment|rules)$", _SHOP + r"reco/\d+(/build)?$"]),
    "platform:ads": ("Реклама: обновить предложения", [_SHOP + r"ads/refresh$"]),
    "platform:plugin": ("Плагин Chrome: отчёты из кабинета WB (точки входа), запись запросов кабинета", [r"^/api/plugin/(trace|entry/\d+)$"]),
    "market:reviews": ("Отправлять ответы на отзывы и вопросы", [_SHOP + r"(reviews|questions)/\d+/send$"]),
    "market:cards": ("Применять правки карточек в WB (тексты, фото, цена), откат, согласование SEO",
                     [_SHOP + r"cards/(\d+/apply|rollback/\d+)$", _SHOP + r"seo_review/\d+/approve$"]),
    "market:ads": ("Реклама: применять действия (пауза, запуск, ставки, минус-фразы…)", [_SHOP + r"ads/(decide|manual)$"]),
}

CLOSED = [r"^/api/(admin|billing|auth|mcp|oauth|assistant|invites|higgsfield)(/|$)", r"^/api/me/",
          r"/(token|ad_token|write_token|secret|invites|members|higgsfield|key_split|paused)(/|$)"]
HUMAN_ONLY = ("force", "price_ack")         


class Denied(Exception):
    pass


def _h(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


def new_token() -> str:
    return PREFIX + secrets.token_urlsafe(32)


def scope_of(path: str) -> str | None:
    """Блок, к которому относится изменение по этому пути (market раньше platform), иначе None."""
    for key in sorted(BLOCKS, key=lambda k: not k.startswith("market:")):
        if any(re.search(p, path) for p in BLOCKS[key][1]):
            return key
    return None


def allowed_blocks(g: dict) -> set[str]:
    lv = g["level"]
    return {b for b in (g.get("blocks") or []) if b in BLOCKS and (lv == "market" or (lv == "platform" and b.startswith("platform:")))}


def check(g: dict, method: str, path: str, body: dict | None) -> None:
    """Можно ли подключению g этот запрос к API платформы. Нельзя — Denied с причиной (её видит нейросеть)."""
    if g.get("kind") == "plugin":
        
        read = method in ("GET", "HEAD") and re.fullmatch(r"/api/plugin/(me|entry_days|download|card/\d+)", path)
        write = method == "POST" and re.fullmatch(r"/api/plugin/(trace|entry/\d+)", path)
        if not (read or write):
            raise Denied("код плагина действует только для функций плагина Chrome")
    if any(re.search(p, path) for p in CLOSED):
        raise Denied("этот раздел нейросетям закрыт (ключи, доступы, оплата, настройки безопасности)")
    m = re.match(r"^/api/shops/(\d+)", path)
    if m and g.get("shops") is not None and int(m.group(1)) not in g["shops"]:
        raise Denied(f"магазин {m.group(1)} не выбран в этом подключении")
    m = re.match(r"^/api/workspaces/(\d+)", path)
    if m and int(m.group(1)) != g["workspace_id"]:
        raise Denied("другой кабинет — не в этом подключении")
    if method in ("GET", "HEAD"):
        return
    blk = scope_of(path)
    if not blk:
        raise Denied("это изменение нейросетям недоступно")
    if blk not in allowed_blocks(g):
        lvl = "в кабинете маркетплейса" if blk.startswith("market:") else "в платформе"
        raise Denied(f"нет права менять {lvl}: «{BLOCKS[blk][0]}» — владелец может разрешить в «Настройки → Нейросети»")
    if isinstance(body, dict) and any(body.get(k) for k in HUMAN_ONLY):
        raise Denied("это подтверждение (снижение цены больше порога / деньги в рекламе) делает только человек на сайте")


def grant_by_token(c, tok: str) -> dict | None:
    if not tok or not tok.startswith(PREFIX):
        return None
    g = c.execute("""SELECT g.*, w.plan FROM mcp_grants g JOIN workspaces w ON w.id=g.workspace_id JOIN users u ON u.id=g.user_id
                     WHERE g.token_hash=%s AND g.revoked_at IS NULL AND (g.expires_at IS NULL OR g.expires_at > now()) AND u.is_active
                       AND EXISTS (SELECT 1 FROM memberships m WHERE m.user_id=g.user_id AND m.workspace_id=g.workspace_id)""",
                  (_h(tok),)).fetchone()
    return g if g and (g.get("kind") == "plugin" or g["plan"] in PLANS) else None


_calls: dict[int, deque] = defaultdict(deque)


def rate_ok(gid: int) -> bool:
    q, now = _calls[gid], time.monotonic()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_MIN:
        return False
    q.append(now)
    return True


def log(c, gid: int, tool: str, ok: bool, *, shop=None, method=None, path=None, error=None, ms=None):
    c.execute("INSERT INTO mcp_log(grant_id,tool,shop_id,method,path,ok,error,ms) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
              (gid, tool, shop, method, (path or "")[:300] or None, ok, (error or "")[:300] or None, ms))
    c.execute("UPDATE mcp_grants SET last_used_at=now(), calls=calls+1 WHERE id=%s", (gid,))


def shops(c, g: dict) -> list[dict]:
    """Магазины подключения: кабинет подключения, доступ пользователя (без доступа поддержки), выбор при подключении."""
    from . import auth
    u = c.execute("SELECT * FROM users WHERE id=%s", (g["user_id"],)).fetchone()
    return [s for s in auth.shops_for(c, u) if s["workspace_id"] == g["workspace_id"] and not s.get("support")
            and (g.get("shops") is None or s["id"] in g["shops"])]



def clean(c, user: dict, ws: int, level: str, blocks: list[str], shop_ids: list[int] | None) -> tuple[str, list[str], list[int] | None]:
    from . import auth
    if level not in LEVELS:
        raise Denied("неизвестный уровень")
    mine = {s["id"] for s in auth.shops_for(c, user) if s["workspace_id"] == ws and not s.get("support")}
    if shop_ids is not None:
        shop_ids = sorted({int(x) for x in shop_ids} & mine)
        if not shop_ids:
            raise Denied("выберите хотя бы один магазин")
    bl = sorted({b for b in blocks or [] if b in BLOCKS})
    if level == "read":
        bl = []
    elif level == "platform":
        bl = [b for b in bl if b.startswith("platform:")]
    return level, bl, shop_ids


def create(c, user: dict, ws: int, name: str, level: str, blocks: list[str], shop_ids: list[int] | None, days: int | None,
           kind: str = "token", client_id: str | None = None) -> tuple[int, str]:
    level, blocks, shop_ids = clean(c, user, ws, level, blocks, shop_ids)
    tok = new_token()
    exp = datetime.now(timezone.utc) + timedelta(days=days) if days else None
    gid = c.execute("""INSERT INTO mcp_grants(user_id,workspace_id,name,kind,client_id,token_hash,token_hint,shops,level,blocks,expires_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (user["id"], ws, (name or "Нейросеть").strip()[:80], kind, client_id, _h(tok), tok[-4:], shop_ids, level, blocks, exp)
                    ).fetchone()["id"]
    return gid, tok


def blocks_list() -> list[dict]:
    return [{"key": k, "title": v[0], "scope": k.split(":")[0]} for k, v in BLOCKS.items()]
