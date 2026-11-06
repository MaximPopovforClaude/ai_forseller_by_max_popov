"""Self-hosted application component."""

import html
import json

from . import actions, auth, cards
from .bots import notify

from .config import site_url
SITE = site_url()


def reviewers(c, shop: int, nm: int) -> list[int]:
    r = c.execute("""SELECT s.user_id FROM staff_articles a JOIN staff s ON s.id=a.staff_id
                     WHERE a.account_id=%s AND a.nm_id=%s AND s.user_id IS NOT NULL""", (shop, nm)).fetchone()
    if r:
        return [r["user_id"]]
    return [x["user_id"] for x in c.execute(
        """SELECT m.user_id FROM memberships m JOIN accounts a ON a.workspace_id=m.workspace_id JOIN users u ON u.id=m.user_id
           WHERE a.id=%s AND u.is_active AND m.role IN ('owner','admin','editor') AND (m.shop_ids IS NULL OR a.id = ANY(m.shop_ids))
           ORDER BY m.role='owner' DESC, m.user_id""", (shop,))]


def can_review(c, user: dict, d: dict) -> bool:
    return user["id"] in (d.get("reviewers") or []) or auth.can(auth.shop_role(c, user, d["account_id"]), "admin")


def _name(c, uid: int | None) -> str:
    u = c.execute("SELECT name, email FROM users WHERE id=%s", (uid,)).fetchone() if uid else None
    return (u["name"] or u["email"]) if u else "—"


def _tell(c, uid: int, text: str):
    r = c.execute("SELECT chat_id FROM notify_settings WHERE user_id=%s AND chat_id IS NOT NULL", (uid,)).fetchone()
    if r:
        notify(c, uid, r["chat_id"], text)


def _event(c, d: dict, state: str, who: int, comment: str | None = None):
    vc = (d["base"] or {}).get("vendorCode")
    c.execute("INSERT INTO news_events(account_id,kind,nm_id,data,notified) VALUES (%s,'seo',%s,%s,true)",
              (d["account_id"], d["nm_id"], json.dumps({"vc": vc, "state": state, "who": _name(c, who), "comment": comment,
                                                         "draft": d["id"], "coverage": (d.get("seo") or {}).get("coverage")}, ensure_ascii=False)))


def submit(c, shop: int, nm: int, uid: int) -> dict:
    d = cards.draft_get(c, shop, nm)
    if not d or not d["changes"]:
        raise actions.ActionDenied("В черновике нет изменений — сначала напишите текст")
    rv = reviewers(c, shop, nm)
    if not rv:
        raise actions.ActionDenied("Некому согласовать: назначьте менеджера артикула или добавьте редактора магазина")
    d = c.execute("""UPDATE card_drafts SET review_state='pending', review_from=%s, review_sent_at=now(), reviewers=%s, review_comment=NULL,
                     reviewed_by=NULL, reviewed_at=NULL WHERE id=%s RETURNING *""", (uid, rv, d["id"])).fetchone()
    _event(c, d, "pending", uid)
    k = d.get("seo") or {}
    sh = c.execute("SELECT coalesce(title,name) t FROM accounts WHERE id=%s", (shop,)).fetchone()["t"]
    txt = (f"📝 <b>SEO на согласование — {html.escape(sh)}</b>\n<code>{html.escape(str(d['base'].get('vendorCode') or nm))}</code> "
           f"(арт. {nm}): новый текст карточки" + (f", покрытие ключей {k['coverage']} %" if k.get("coverage") is not None else "") +
           f".\nОтправил(а): {html.escape(_name(c, uid))}.\nПроверить и согласовать: {SITE} → «SEO» → «На согласовании».")
    for r in rv:
        if r != uid:
            _tell(c, r, txt)
    c.commit()
    return {"reviewers": [_name(c, r) for r in rv]}


def approve(c, user: dict, draft_id: int) -> dict:
    d = c.execute("SELECT * FROM card_drafts WHERE id=%s", (draft_id,)).fetchone()
    if not d or d["status"] != "draft" or d["review_state"] != "pending":
        raise actions.ActionDenied("Этот черновик уже не ждёт согласования")
    if not can_review(c, user, d):
        raise actions.ActionDenied("Согласовать может менеджер артикула или администратор магазина")
    res = cards.apply(c, d["account_id"], d["nm_id"], user["id"])       
    c.execute("UPDATE card_drafts SET review_state='approved', reviewed_by=%s, reviewed_at=now() WHERE id=%s", (user["id"], d["id"]))
    _event(c, d, "approved" if res["status"] == "applied" else "error", user["id"], "; ".join(res.get("errors") or []) or None)
    if d["review_from"] and d["review_from"] != user["id"]:
        _tell(c, d["review_from"], f"✅ SEO <code>{html.escape(str(d['base'].get('vendorCode') or d['nm_id']))}</code> согласовано "
              f"({html.escape(_name(c, user['id']))})" + (" и загружено в WB." if res["status"] == "applied" else f", но WB: {html.escape('; '.join(res['errors']))[:500]}"))
    c.commit()
    return res


def send_back(c, user: dict, draft_id: int, comment: str) -> dict:
    d = c.execute("SELECT * FROM card_drafts WHERE id=%s", (draft_id,)).fetchone()
    if not d or d["status"] != "draft" or d["review_state"] != "pending":
        raise actions.ActionDenied("Этот черновик уже не ждёт согласования")
    if not can_review(c, user, d):
        raise actions.ActionDenied("Вернуть может менеджер артикула или администратор магазина")
    comment = (comment or "").strip()[:2000]
    if not comment:
        raise actions.ActionDenied("Напишите, что исправить")
    c.execute("UPDATE card_drafts SET review_state='returned', review_comment=%s, reviewed_by=%s, reviewed_at=now() WHERE id=%s",
              (comment, user["id"], d["id"]))
    _event(c, d, "returned", user["id"], comment)
    if d["review_from"] and d["review_from"] != user["id"]:
        _tell(c, d["review_from"], f"↩️ SEO <code>{html.escape(str(d['base'].get('vendorCode') or d['nm_id']))}</code> вернули на доработку "
              f"({html.escape(_name(c, user['id']))}): {html.escape(comment)}\n{SITE} → «SEO»")
    c.commit()
    return {"ok": True}


def pending(c, user: dict, shop: int) -> list[dict]:
    rows = c.execute("""SELECT id, nm_id, base->>'vendorCode' vc, base->>'title' old_title, changes, seo, review_from, review_sent_at, reviewers
                        FROM card_drafts WHERE account_id=%s AND status='draft' AND review_state='pending' ORDER BY review_sent_at""", (shop,)).fetchall()
    return [{**{k: r[k] for k in ("id", "nm_id", "vc", "old_title", "review_sent_at")}, "title": r["changes"].get("title"),
             "coverage": (r["seo"] or {}).get("coverage"), "from": _name(c, r["review_from"]),
             "reviewers": [_name(c, x) for x in r["reviewers"] or []], "mine": can_review(c, user, {**r, "account_id": shop})} for r in rows]
