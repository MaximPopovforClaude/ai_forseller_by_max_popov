"""Self-hosted application component."""

import html
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel

from . import auth, visual, visual_ai
from .web import _audit, conn, current_user

router = APIRouter()


def _shop(c, u, shop_id: int, need: str) -> dict:
    if not auth.can(auth.shop_role(c, u, shop_id), need):
        raise HTTPException(403, "Нет доступа к магазину" if need == "viewer" else "Нужна роль «редактор» или выше")
    return c.execute("SELECT id, workspace_id, marketplace FROM accounts WHERE id=%s", (shop_id,)).fetchone()


def _err(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except visual.VisualError as e:
        raise HTTPException(400, str(e)) from None


@router.get("/api/shops/{shop_id}/visual")
def vis_list(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "viewer")
    rows = c.execute("""SELECT p.id, p.nm_id, p.title, p.updated_at, n.vendor_code, n.data->>'subjectName' subject,
                               (SELECT count(*) FROM vis_files f WHERE f.project_id=p.id AND f.kind='source') sources,
                               (SELECT max(version) FROM vis_briefs b WHERE b.project_id=p.id) briefs,
                               (SELECT state FROM vis_briefs b WHERE b.project_id=p.id ORDER BY version DESC LIMIT 1) brief_state,
                               p.passport_id IS NOT NULL passport
                        FROM vis_projects p LEFT JOIN nomenclature n ON n.account_id=p.account_id AND n.nm_id=p.nm_id
                        WHERE p.account_id=%s AND NOT p.archived ORDER BY p.updated_at DESC LIMIT 500""", (shop_id,)).fetchall()
    from .cardcompare import photo
    for r in rows:
        r["photo"] = photo(c, r["nm_id"]) if r["nm_id"] else None
    pend = c.execute("SELECT count(*) n FROM vis_briefs WHERE account_id=%s AND state='pending'", (shop_id,)).fetchone()["n"]
    return jsonable_encoder({"rows": rows, "pending": pend, "can_edit": auth.can(auth.shop_role(c, u, shop_id), "editor")})


@router.get("/api/shops/{shop_id}/visual_gallery")
def vis_gallery(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    """«📚 База фото» всего магазина: отрисованное и доработанное по всем товарам + что одобрено в базу."""
    _shop(c, u, shop_id, "viewer")
    rows = c.execute("""SELECT f.id file_id, coalesce(r.title, ph.title, f.name) title, r.model, r.task, coalesce(r.project_id, ph.project_id) project_id,
                               p.title project, p.nm_id, n.vendor_code, ph.id IS NOT NULL in_base, coalesce(ph.created_at, r.finished_at, f.created_at) at,
                               CASE WHEN r.slot LIKE 'first:%%' THEN coalesce(substring(r.slot from '[0-9]+')::int, 0)
                                    WHEN r.slot LIKE 'slide:%%' THEN 100 + coalesce(substring(r.slot from '[0-9]+')::int, 0) ELSE 999 END so
                        FROM vis_files f
                        LEFT JOIN vis_renders r ON r.file_id=f.id AND r.state='done'
                        LEFT JOIN LATERAL (SELECT id, title, project_id, created_at FROM vis_photos x WHERE x.file_id=f.id ORDER BY id LIMIT 1) ph ON true
                        LEFT JOIN vis_projects p ON p.id=coalesce(r.project_id, ph.project_id)
                        LEFT JOIN nomenclature n ON n.account_id=p.account_id AND n.nm_id=p.nm_id
                        WHERE f.account_id=%s AND (r.id IS NOT NULL OR ph.id IS NOT NULL) AND coalesce(p.archived, false) = false
                        ORDER BY at DESC LIMIT 1500""", (shop_id,)).fetchall()
    return jsonable_encoder({"rows": rows, "can_edit": auth.can(auth.shop_role(c, u, shop_id), "editor")})


class NewIn(BaseModel):
    nm_id: int | None = None
    title: str = ""
    description: str = ""


@router.post("/api/shops/{shop_id}/visual")
def vis_create(shop_id: int, body: NewIn, u=Depends(current_user), c=Depends(conn)):
    s = _shop(c, u, shop_id, "editor")
    pid = _err(visual.create, c, shop_id, u["id"], body.nm_id, body.title, body.description)
    _audit(c, u, s["workspace_id"], "visual/create", {"shop": shop_id, "project": pid, "nm": body.nm_id})
    c.commit()
    added = visual.ensure_sources(c, shop_id, pid, u["id"])      
    c.commit()
    return {"id": pid, "card_photos": added}


def _state(c, u, shop_id: int, pid: int) -> dict:
    from . import assistant, higgsfield as hf, seo_review, visual_render as vr
    p = _err(visual.project, c, shop_id, pid)
    pas = None
    if p["passport_id"]:
        f = c.execute("SELECT id, name, meta, created_at FROM vis_files WHERE id=%s", (p["passport_id"],)).fetchone()
        if f:
            m = f["meta"] or {}
            pas = {"id": f["id"], "name": f["name"], "models": [x.get("name") for x in m.get("models") or []], "state": m.get("state"),
                   "specs": next((x.get("specs") for x in m.get("models") or [] if x.get("name") == p["passport_model"]), None)}
    b = visual.brief_latest(c, pid)
    if b:
        b = {**b, "reviewers_names": [seo_review._name(c, x) for x in b["reviewers"] or []], "reviewed_by_name": seo_review._name(c, b["reviewed_by"]),
             "can_review": b["state"] == "pending" and (u["id"] in (b["reviewers"] or []) or auth.can(auth.shop_role(c, u, shop_id), "admin"))}
    return jsonable_encoder({
        "project": {k: p[k] for k in ("id", "nm_id", "title", "description", "main_key", "passport_model", "passport_guess", "competitors",
                                       "answers", "goals", "note", "updated_at")},
        "vendor_code": (c.execute("SELECT vendor_code FROM nomenclature WHERE account_id=%s AND nm_id=%s", (shop_id, p["nm_id"])).fetchone() or {}).get("vendor_code")
        if p["nm_id"] else None,
        "sources": visual.files(c, pid, "source"), "passport": pas, "passports": visual.passports(c, shop_id),
        "jobs": visual_ai.jobs(c, pid), "brief": b, "versions": visual.briefs(c, shop_id, pid),
        "questions": {"groups": visual_ai.R.GROUPS, "q": visual_ai.R.QUESTIONS},
        "can_edit": auth.can(auth.shop_role(c, u, shop_id), "editor"), "ai": bool(assistant.access(c, shop_id).get("ok")),
        "will_review": [seo_review._name(c, x) for x in seo_review.reviewers(c, shop_id, p["nm_id"] or 0)],
        "hf": hf.connected(c, shop_id), "hf_models": [{"id": k, "title": m["title"]} for k, m in hf.MODELS.items()],
        "render_models": vr.models(c, shop_id, u["id"])})


@router.get("/api/shops/{shop_id}/visual/{pid}")
def vis_get(shop_id: int, pid: int, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "viewer")
    return _state(c, u, shop_id, pid)


class EditIn(BaseModel):
    title: str | None = None
    description: str | None = None
    main_key: str | None = None
    note: str | None = None
    passport_model: str | None = None
    answers: dict | None = None
    goals: dict | None = None
    comp_add: int | None = None
    comp_remove: int | None = None
    archived: bool | None = None


@router.put("/api/shops/{shop_id}/visual/{pid}")
def vis_edit(shop_id: int, pid: int, body: EditIn, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "editor")
    p = _err(visual.project, c, shop_id, pid)
    sets, vals = [], []
    for f in ("title", "description", "main_key", "note", "passport_model"):
        v = getattr(body, f)
        if v is not None:
            sets.append(f"{f}=%s")
            vals.append(v.strip()[:6000] or None if f != "title" else (v.strip()[:300] or p["title"]))
    for f in ("answers", "goals"):
        v = getattr(body, f)
        if v is not None:
            sets.append(f"{f}=%s")
            vals.append(json.dumps(v, ensure_ascii=False))
    if body.comp_add or body.comp_remove:
        comp = dict(p["competitors"] or {})
        man, exc = list(comp.get("manual") or []), list(comp.get("excluded") or [])
        if body.comp_add and body.comp_add not in man:
            man.append(body.comp_add)
            exc = [x for x in exc if x != body.comp_add]
        if body.comp_remove:
            man = [x for x in man if x != body.comp_remove]
            exc.append(body.comp_remove)
            comp["items"] = [x for x in comp.get("items") or [] if x.get("id") != body.comp_remove]
        comp.update(manual=man, excluded=exc)
        sets.append("competitors=%s")
        vals.append(json.dumps(comp, ensure_ascii=False))
    if body.archived is not None:
        sets.append("archived=%s")
        vals.append(body.archived)
    if sets:
        c.execute(f"UPDATE vis_projects SET {', '.join(sets)}, updated_at=now() WHERE id=%s", (*vals, pid))
        c.commit()
    return _state(c, u, shop_id, pid)


@router.post("/api/shops/{shop_id}/visual/{pid}/files")
async def vis_upload(shop_id: int, pid: int, request: Request, kind: str = "source", name: str = "", u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "editor")
    if kind not in ("source", "passport"):
        raise HTTPException(400, "Неизвестный тип файла")
    _err(visual.project, c, shop_id, pid)
    raw = await request.body()
    r = _err(visual.save, c, shop_id, pid, kind, name, raw, u["id"], "загрузка")
    if kind == "passport":
        c.execute("UPDATE vis_projects SET passport_id=%s, passport_model=NULL, passport_guess=NULL WHERE id=%s", (r["id"], pid))
    visual.touch(c, pid)
    c.commit()
    if kind == "passport":
        visual_ai.start(shop_id, pid, ["passport"], u["id"])
    return r


class LinkIn(BaseModel):
    url: str
    kind: str = "source"


@router.post("/api/shops/{shop_id}/visual/{pid}/link")
def vis_link(shop_id: int, pid: int, body: LinkIn, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "editor")
    _err(visual.project, c, shop_id, pid)
    if body.kind not in ("source", "passport"):
        raise HTTPException(400, "Неизвестный тип файла")
    got = _err(visual.fetch_link, body.url, "images" if body.kind == "source" else "one")
    saved, skipped = [], []
    for name, raw, ct in got:
        try:
            r = visual.save(c, shop_id, pid, body.kind, name, raw, u["id"], body.url[:300], ct)
            if not r.get("dup"):
                saved.append(r)
            if body.kind == "passport":
                c.execute("UPDATE vis_projects SET passport_id=%s, passport_model=NULL, passport_guess=NULL WHERE id=%s", (r["id"], pid))
                break
        except visual.VisualError as e:
            skipped.append(str(e))
    if not saved and not (body.kind == "passport" and got and not skipped):
        c.rollback()
        raise HTTPException(400, "; ".join(skipped[:3]) or "По ссылке не нашлось подходящих файлов")
    visual.touch(c, pid)
    c.commit()
    if body.kind == "passport":
        visual_ai.start(shop_id, pid, ["passport"], u["id"])
    return {"saved": len(saved), "skipped": skipped[:10]}


@router.post("/api/shops/{shop_id}/visual/{pid}/from_card")
def vis_from_card(shop_id: int, pid: int, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "editor")
    p = _err(visual.project, c, shop_id, pid)
    if not p["nm_id"]:
        raise HTTPException(400, "У проекта нет артикула WB")
    n = _err(visual.import_card_photos, c, shop_id, pid, p["nm_id"], u["id"])
    visual.touch(c, pid)
    c.commit()
    return {"saved": n}


@router.delete("/api/shops/{shop_id}/visual/{pid}/files/{fid}")
def vis_file_del(shop_id: int, pid: int, fid: int, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "editor")
    c.execute("DELETE FROM vis_files WHERE id=%s AND project_id=%s AND account_id=%s AND kind='source'", (fid, pid, shop_id))
    c.commit()
    return {"ok": True}


class PassIn(BaseModel):
    file_id: int | None = None


@router.put("/api/shops/{shop_id}/visual/{pid}/passport")
def vis_passport(shop_id: int, pid: int, body: PassIn, u=Depends(current_user), c=Depends(conn)):
    """Взять уже загруженный паспорт магазина (один паспорт — на несколько похожих товаров) или отвязать."""
    _shop(c, u, shop_id, "editor")
    _err(visual.project, c, shop_id, pid)
    if body.file_id and not c.execute("SELECT 1 FROM vis_files WHERE id=%s AND account_id=%s AND kind='passport'", (body.file_id, shop_id)).fetchone():
        raise HTTPException(404, "Нет такого паспорта")
    c.execute("UPDATE vis_projects SET passport_id=%s, passport_model=NULL, passport_guess=NULL, updated_at=now() WHERE id=%s", (body.file_id, pid))
    c.commit()
    if body.file_id:
        visual_ai.start(shop_id, pid, ["passport"], u["id"])
    return _state(c, u, shop_id, pid)


@router.get("/api/shops/{shop_id}/visual_file/{fid}")
def vis_file(shop_id: int, fid: int, thumb: int = 0, w: int = 0, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "viewer")
    if thumb or w:            
        size = 1600 if w else 360
        return Response(_err(visual.thumb, c, shop_id, fid, size), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
    r = _err(visual.file_path, c, shop_id, fid)
    return FileResponse(r["path"], media_type=r["mime"], filename=r["name"], content_disposition_type="inline")


class RunIn(BaseModel):
    steps: list[str]
    first_n: int = 3
    render_models: list[str] = []      
    render_scope: str = "all"          


@router.post("/api/shops/{shop_id}/visual/{pid}/run")
def vis_run(shop_id: int, pid: int, body: RunIn, u=Depends(current_user), c=Depends(conn)):
    s = _shop(c, u, shop_id, "editor")
    p = _err(visual.project, c, shop_id, pid)
    steps = [x for x in visual_ai.STEPS if x in body.steps]
    if not steps:
        raise HTTPException(400, "Нет шагов")
    if "passport" in steps and not p["passport_id"]:
        steps.remove("passport")
    from . import assistant
    a = assistant.access(c, shop_id)
    if not a.get("ok"):
        raise HTTPException(400, a.get("reason") or "Нейросеть недоступна")
    render = None
    if body.render_models:
        from . import visual_render as vr
        mods = _rerr(vr.selected, c, shop_id, body.render_models, u["id"])
        render = {"models": mods, "scope": "first" if body.render_scope == "first" else "all"}
    visual.ensure_sources(c, shop_id, pid, u["id"])              
    _audit(c, u, s["workspace_id"], "visual/run", {"shop": shop_id, "project": pid, "steps": steps, "render": render})
    c.commit()
    if not visual_ai.start(shop_id, pid, steps, u["id"], max(1, min(6, body.first_n)), render):
        raise HTTPException(409, "Нейросеть уже работает над этим товаром — дождитесь")
    return _state(c, u, shop_id, pid)



@router.get("/api/shops/{shop_id}/visual_briefs")
def vis_briefs(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "viewer")
    return jsonable_encoder({"rows": visual.briefs(c, shop_id)})


@router.get("/api/shops/{shop_id}/visual_brief/{bid}")
def vis_brief(shop_id: int, bid: int, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "viewer")
    b = c.execute("SELECT * FROM vis_briefs WHERE id=%s AND account_id=%s", (bid, shop_id)).fetchone()
    if not b:
        raise HTTPException(404, "Нет такого ТЗ")
    return jsonable_encoder(b)


class BriefIn(BaseModel):
    data: dict


@router.put("/api/shops/{shop_id}/visual/{pid}/brief")
def vis_brief_save(shop_id: int, pid: int, body: BriefIn, u=Depends(current_user), c=Depends(conn)):
    """Правка ТЗ менеджером: черновик правится на месте, отправленное/согласованное — новой версией (старая остаётся в базе)."""
    _shop(c, u, shop_id, "editor")
    _err(visual.brief_save, c, shop_id, pid, "graphics", body.data, u["id"], new_version=False)
    visual.touch(c, pid)
    c.commit()
    return _state(c, u, shop_id, pid)


@router.post("/api/shops/{shop_id}/visual/{pid}/brief/submit")
def vis_brief_submit(shop_id: int, pid: int, u=Depends(current_user), c=Depends(conn)):
    from . import seo_review
    s = _shop(c, u, shop_id, "editor")
    p = _err(visual.project, c, shop_id, pid)
    b = visual.brief_latest(c, pid)
    if not b:
        raise HTTPException(400, "Сначала соберите ТЗ")
    rv = seo_review.reviewers(c, shop_id, p["nm_id"] or 0)
    if not rv:
        raise HTTPException(400, "Некому согласовать: назначьте менеджера артикула или добавьте редактора магазина")
    c.execute("UPDATE vis_briefs SET state='pending', reviewers=%s, review_from=%s, review_comment=NULL, reviewed_by=NULL, reviewed_at=NULL, "
              "updated_at=now() WHERE id=%s", (rv, u["id"], b["id"]))
    sh = c.execute("SELECT coalesce(title,name) t FROM accounts WHERE id=%s", (shop_id,)).fetchone()["t"]
    txt = (f"🎨 <b>ТЗ на визуал — на согласование ({html.escape(sh)})</b>\n{html.escape(p['title'][:120])}"
           + (f" (арт. {p['nm_id']})" if p["nm_id"] else "") + f", версия {b['version']}.\nОтправил(а): {html.escape(seo_review._name(c, u['id']))}."
           f"\nПроверить: {seo_review.SITE} → «Визуал».")
    for r in rv:
        if r != u["id"]:
            seo_review._tell(c, r, txt)
    _audit(c, u, s["workspace_id"], "visual/brief_submit", {"shop": shop_id, "project": pid, "brief": b["id"]})
    c.commit()
    return _state(c, u, shop_id, pid)


@router.post("/api/shops/{shop_id}/visual/{pid}/brief/to_render")
def vis_brief_to_render(shop_id: int, pid: int, u=Depends(current_user), c=Depends(conn)):
    """«Отправить в отрисовку»: нажавший (редактор) согласует последнее ТЗ сам, дальше — вкладка «Отрисовка»."""
    from . import visual_render as vr
    s = _shop(c, u, shop_id, "editor")
    _err(visual.project, c, shop_id, pid)
    b = _rerr(vr.approve_brief, c, pid, u["id"], "отправлено в отрисовку без согласования менеджером")
    _audit(c, u, s["workspace_id"], "visual/brief_to_render", {"shop": shop_id, "project": pid, "brief": b["id"]})
    c.commit()
    return _state(c, u, shop_id, pid)


class ReviewIn(BaseModel):
    ok: bool
    comment: str = ""


@router.post("/api/shops/{shop_id}/visual/{pid}/brief/review")
def vis_brief_review(shop_id: int, pid: int, body: ReviewIn, u=Depends(current_user), c=Depends(conn)):
    from . import seo_review
    s = _shop(c, u, shop_id, "viewer")
    b = visual.brief_latest(c, pid)
    if not b or b["state"] != "pending" or b["account_id"] != shop_id:
        raise HTTPException(400, "Это ТЗ не ждёт согласования")
    if not (u["id"] in (b["reviewers"] or []) or auth.can(auth.shop_role(c, u, shop_id), "admin")):
        raise HTTPException(403, "Согласует менеджер артикула или администратор магазина")
    if not body.ok and not body.comment.strip():
        raise HTTPException(400, "Напишите, что исправить")
    c.execute("UPDATE vis_briefs SET state=%s, review_comment=%s, reviewed_by=%s, reviewed_at=now(), updated_at=now() WHERE id=%s",
              ("approved" if body.ok else "returned", body.comment.strip()[:2000] or None, u["id"], b["id"]))
    if b["review_from"] and b["review_from"] != u["id"]:
        seo_review._tell(c, b["review_from"], ("✅ ТЗ на визуал согласовано" if body.ok else "↩️ ТЗ на визуал вернули на доработку") +
                         f" ({html.escape(seo_review._name(c, u['id']))}), версия {b['version']}" +
                         (f": {html.escape(body.comment.strip()[:500])}" if body.comment.strip() else "") + f"\n{seo_review.SITE} → «Визуал»")
    _audit(c, u, s["workspace_id"], "visual/brief_review", {"shop": shop_id, "project": pid, "brief": b["id"], "ok": body.ok})
    c.commit()
    return _state(c, u, shop_id, pid)


@router.get("/api/shops/{shop_id}/visual_brief/{bid}/text")
def vis_brief_text(shop_id: int, bid: int, u=Depends(current_user), c=Depends(conn)):
    """ТЗ текстом — переслать дизайнеру."""
    _shop(c, u, shop_id, "viewer")
    b = c.execute("SELECT b.*, p.title FROM vis_briefs b JOIN vis_projects p ON p.id=b.project_id WHERE b.id=%s AND b.account_id=%s",
                  (bid, shop_id)).fetchone()
    if not b:
        raise HTTPException(404, "Нет такого ТЗ")
    return PlainTextResponse(brief_text(b), headers={"Content-Disposition": f'attachment; filename="tz_{bid}_v{b["version"]}.txt"'})


def brief_text(b: dict) -> str:
    d = b["data"] or {}
    h = d.get("header") or {}
    L = [f"ТЗ НА ИНФОГРАФИКУ: {b['title']}" + (f" (арт. WB {b['nm_id']})" if b["nm_id"] else "") + f" — версия {b['version']}", ""]
    L += ["ШАПКА ТЗ. ВВОДНЫЕ ПРАВИЛА:", *[f"- {x}" for x in h.get("rules") or []]]
    for k, t in (("style", "Стилистика"), ("palette", "Палитра"), ("fonts", "Шрифты"), ("keep", "Нельзя менять"), ("main_key", "Основной запрос на 1-й слайд")):
        if h.get(k):
            L.append(f"{t}: {h[k]}")
    for f in d.get("first_slides") or []:
        L += ["", f"СЛАЙД 1 — вариант {f.get('variant')}: {f.get('style')}", f"Надпись: «{f.get('headline')}»",
              f"Триггеры: {', '.join(f.get('triggers') or [])}", f"Композиция: {f.get('composition')}", f"Фон: {f.get('background')}",
              *[f"- {x}" for x in f.get("how") or []], f"Исходники: {', '.join('#' + str(x) for x in f.get('sources') or [])}", f"Промпт: {f.get('prompt')}"]
    for i, s in enumerate(d.get("slides") or [], 2):
        L += ["", f"СЛАЙД {i}: {s.get('goal')}", f"Надпись сверху: «{s.get('headline')}»"]
        if s.get("texts"):
            L.append("Тексты: " + " / ".join(f"«{x}»" for x in s["texts"]))
        L += [*[f"- {x}" for x in s.get("how") or []], f"Что нужно: {s.get('needs')}", f"Что нарисовать: {s.get('composition')}",
              f"Фон: {s.get('background')}", f"Исходники: {', '.join('#' + str(x) for x in s.get('sources') or [])}"]
        if s.get("specs_check"):
            L.append("Сверить цифры: " + "; ".join(s["specs_check"]))
        L.append(f"Промпт: {s.get('prompt')}")
    if d.get("funnels"):
        L += ["", "ВОРОНКИ (порядок слайдов 2-6):", *[f"- {f.get('name')}: {' → '.join(f.get('slides') or [])} ({f.get('idea')})" for f in d["funnels"]]]
    return "\n".join(str(x) for x in L)


def brief_html(b: dict, src_names: dict[int, str]) -> str:
    """ТЗ для дизайнера — HTML (открывается в браузере и в Word, печатается). Исходники — по именам файлов в папке «исходники»."""
    d, e = b["data"] or {}, html.escape
    h = d.get("header") or {}

    def src(ids) -> str:
        return ", ".join(e(src_names.get(int(x), f"#{x}")) for x in ids or [] if str(x).isdigit()) or "—"

    def row(t, v) -> str:
        return f"<tr><th>{e(t)}</th><td>{v}</td></tr>" if v else ""

    def ul(xs) -> str:
        return "<ul>" + "".join(f"<li>{e(str(x))}</li>" for x in xs) + "</ul>" if xs else ""
    o = [f"<!doctype html><html><head><meta charset='utf-8'><title>ТЗ v{b['version']} — {e(b['title'])}</title><style>"
         "body{font:15px/1.5 Arial,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#222}"
         "h1{font-size:22px}h2{font-size:18px;margin-top:28px;border-bottom:2px solid #333;padding-bottom:4px}"
         "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;padding:6px 8px;vertical-align:top;text-align:left}"
         "th{width:180px;background:#f4f4f4}.pr{font-family:monospace;font-size:12px;color:#555;white-space:pre-wrap}</style></head><body>",
         f"<h1>ТЗ на инфографику: {e(b['title'])}</h1><p>" + (f"Артикул WB {b['nm_id']} · " if b["nm_id"] else "") + f"версия {b['version']}</p>"
         "<p><i>Исходник #N в тексте — файл, имя которого начинается с «N_», в папке «исходники» этого архива.</i></p>",
         "<h2>Шапка ТЗ — вводные правила</h2>", ul(h.get("rules") or []), "<table>"]
    for k, t in (("style", "Стилистика"), ("palette", "Палитра"), ("fonts", "Шрифты"), ("keep", "Нельзя менять"), ("main_key", "Основной запрос на 1-й слайд")):
        o.append(row(t, e(str(h[k])) if h.get(k) else ""))
    o.append("</table>")
    for f in d.get("first_slides") or []:
        o += [f"<h2>Слайд 1 — вариант {e(str(f.get('variant') or ''))}: {e(str(f.get('style') or ''))}</h2><table>",
              row("Надпись", f"<b>«{e(str(f.get('headline') or ''))}»</b>"), row("Триггеры", e(", ".join(f.get("triggers") or []))),
              row("Композиция", e(str(f.get("composition") or ""))), row("Фон", e(str(f.get("background") or ""))),
              row("Как сделать", ul(f.get("how") or [])), row("Исходники", src(f.get("sources"))),
              row("Промпт для нейросети", f"<div class='pr'>{e(str(f.get('prompt') or ''))}</div>"), "</table>"]
    for i, sl in enumerate(d.get("slides") or [], 2):
        o += [f"<h2>Слайд {i}: {e(str(sl.get('goal') or ''))}</h2><table>", row("Надпись сверху", f"<b>«{e(str(sl.get('headline') or ''))}»</b>"),
              row("Тексты", "<br>".join(f"«{e(str(x))}»" for x in sl.get("texts") or [])), row("Как сделать", ul(sl.get("how") or [])),
              row("Что нужно", e(str(sl.get("needs") or ""))), row("Что нарисовать", e(str(sl.get("composition") or ""))),
              row("Фон", e(str(sl.get("background") or ""))), row("Исходники", src(sl.get("sources"))),
              row("Сверить цифры", ul(sl.get("specs_check") or [])),
              row("Промпт для нейросети", f"<div class='pr'>{e(str(sl.get('prompt') or ''))}</div>"), "</table>"]
    if d.get("funnels"):
        o += ["<h2>Воронки (порядок слайдов 2–6)</h2>",
              ul([f"{f.get('name')}: {' → '.join(f.get('slides') or [])} ({f.get('idea')})" for f in d["funnels"]])]
    return "".join(o) + "</body></html>"


class AdaptIn(BaseModel):
    nm_id: int


@router.post("/api/shops/{shop_id}/visual_brief/{bid}/apply")
def vis_brief_apply(shop_id: int, bid: int, body: AdaptIn, u=Depends(current_user), c=Depends(conn)):
    """То же ТЗ — на другой артикул: слайды и их суть те же, фото и характеристики — нового товара. Новое ТЗ — черновик, согласуют как обычно."""
    from . import assistant
    s = _shop(c, u, shop_id, "editor")
    a = assistant.access(c, shop_id)
    if not a.get("ok"):
        raise HTTPException(400, a.get("reason") or "Нейросеть недоступна")
    try:
        pid = visual_ai.adapt_start(c, shop_id, bid, body.nm_id, u["id"])
    except (visual_ai.StepError, visual.VisualError) as e:
        raise HTTPException(400, str(e)) from None
    _audit(c, u, s["workspace_id"], "visual/brief_apply", {"shop": shop_id, "brief": bid, "nm": body.nm_id, "project": pid})
    c.commit()
    return {"project_id": pid}


@router.get("/api/shops/{shop_id}/visual_brief/{bid}/zip")
def vis_brief_zip(shop_id: int, bid: int, u=Depends(current_user), c=Depends(conn)):
    """Пакет для дизайнера: ТЗ (HTML для чтения/печати + текст) и все исходники товара, паспорт, логотип."""
    import re
    import tempfile
    import zipfile
    from pathlib import Path
    from starlette.background import BackgroundTask
    _shop(c, u, shop_id, "viewer")
    b = c.execute("SELECT b.*, p.title, p.passport_id FROM vis_briefs b JOIN vis_projects p ON p.id=b.project_id WHERE b.id=%s AND b.account_id=%s",
                  (bid, shop_id)).fetchone()
    if not b:
        raise HTTPException(404, "Нет такого ТЗ")
    safe = lambda x: re.sub(r'[\\/:*?"<>|\s]+', "_", x).strip("_")[:80] or "file"   
    files = [("исходники", r) for r in c.execute("SELECT id, name, path FROM vis_files WHERE project_id=%s AND kind='source' ORDER BY id",
                                                   (b["project_id"],))]
    if b["passport_id"]:
        files += [("паспорт", r) for r in c.execute("SELECT id, name, path FROM vis_files WHERE id=%s", (b["passport_id"],))]
    files += [("логотип", r) for r in c.execute("""SELECT f.id, f.name, f.path FROM vis_brand v JOIN vis_files f ON f.id=v.logo_id
                                                    WHERE v.account_id=%s""", (shop_id,))]
    names = {r["id"]: f"{d}/{r['id']}_{safe(r['name'] or 'file')}" for d, r in files}
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    with zipfile.ZipFile(tmp, "w") as z:
        z.writestr(f"ТЗ_v{b['version']}.html", brief_html(b, names), zipfile.ZIP_DEFLATED)
        z.writestr(f"ТЗ_v{b['version']}.txt", brief_text(b), zipfile.ZIP_DEFLATED)
        for _, r in files:
            if Path(r["path"]).exists():
                z.write(r["path"], names[r["id"]], zipfile.ZIP_STORED)
    tmp.close()
    return FileResponse(tmp.name, media_type="application/zip", filename=f"tz_{bid}_v{b['version']}.zip",
                        background=BackgroundTask(lambda: Path(tmp.name).unlink(missing_ok=True)))



class BrandIn(BaseModel):
    colors: str = ""
    fonts: str = ""
    notes: str = ""


@router.get("/api/shops/{shop_id}/visual_brand")
def vis_brand(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "viewer")
    return jsonable_encoder({**visual.brand(c, shop_id), "passports": visual.passports(c, shop_id),
                             "can_edit": auth.can(auth.shop_role(c, u, shop_id), "editor")})


@router.put("/api/shops/{shop_id}/visual_brand")
def vis_brand_save(shop_id: int, body: BrandIn, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "editor")
    c.execute("""INSERT INTO vis_brand(account_id,colors,fonts,notes,updated_by) VALUES (%s,%s,%s,%s,%s)
                 ON CONFLICT (account_id) DO UPDATE SET colors=EXCLUDED.colors, fonts=EXCLUDED.fonts, notes=EXCLUDED.notes,
                 updated_by=EXCLUDED.updated_by, updated_at=now()""", (shop_id, body.colors[:1000], body.fonts[:1000], body.notes[:4000], u["id"]))
    c.commit()
    return {"ok": True}



def _rerr(fn, *a, **kw):
    from . import visual_render as vr
    try:
        return fn(*a, **kw)
    except (vr.RenderError, visual.VisualError) as e:
        raise HTTPException(400, str(e)) from None


@router.get("/api/shops/{shop_id}/visual/{pid}/render")
def vis_render_state(shop_id: int, pid: int, u=Depends(current_user), c=Depends(conn)):
    from . import visual_render as vr
    _shop(c, u, shop_id, "viewer")
    _err(visual.project, c, shop_id, pid)
    vr.ensure_running(c, pid)
    return jsonable_encoder({"plan": vr.plan(c, shop_id, pid), "models": vr.models(c, shop_id, u["id"]), "renders": vr.renders(c, pid),
                             "photos": vr.photos(c, shop_id, pid), "shared": vr.photos(c, shop_id, None),
                             "can_edit": auth.can(auth.shop_role(c, u, shop_id), "editor")})


class EstIn(BaseModel):
    slots: list[str] = []
    models: list[str] = []
    per: int = 1
    edit_n: int = 0


@router.post("/api/shops/{shop_id}/visual/{pid}/render/estimate")
def vis_render_estimate(shop_id: int, pid: int, body: EstIn, u=Depends(current_user), c=Depends(conn)):
    from . import visual_render as vr
    _shop(c, u, shop_id, "editor")
    _err(visual.project, c, shop_id, pid)
    n = body.edit_n or len(body.slots) * max(1, min(3, body.per))
    return _rerr(vr.estimate, c, shop_id, {m: n for m in body.models}, u["id"])


class DrawIn(BaseModel):
    slots: list[str]
    models: list[str]
    per: int = 1


@router.post("/api/shops/{shop_id}/visual/{pid}/render")
def vis_render_start(shop_id: int, pid: int, body: DrawIn, u=Depends(current_user), c=Depends(conn)):
    from . import visual_render as vr
    s = _shop(c, u, shop_id, "editor")
    _err(visual.project, c, shop_id, pid)
    batch = _rerr(vr.start, c, shop_id, pid, u["id"], body.slots, body.models, max(1, min(3, body.per)))
    _audit(c, u, s["workspace_id"], "visual/render", {"shop": shop_id, "project": pid, "slots": body.slots, "models": body.models, "per": body.per})
    c.commit()
    vr.kick()
    return {"batch": batch}


@router.post("/api/shops/{shop_id}/visual/{pid}/render/stop")
def vis_render_stop(shop_id: int, pid: int, u=Depends(current_user), c=Depends(conn)):
    from . import visual_render as vr
    s = _shop(c, u, shop_id, "editor")
    _err(visual.project, c, shop_id, pid)
    n = vr.stop(c, shop_id, pid)
    _audit(c, u, s["workspace_id"], "visual/render_stop", {"shop": shop_id, "project": pid, "n": n})
    c.commit()
    return {"stopped": n}


@router.delete("/api/shops/{shop_id}/visual/{pid}/render/{rid}")
def vis_render_delete(shop_id: int, pid: int, rid: int, u=Depends(current_user), c=Depends(conn)):
    from . import visual_render as vr
    s = _shop(c, u, shop_id, "editor")
    _rerr(vr.delete, c, shop_id, pid, rid)
    _audit(c, u, s["workspace_id"], "visual/render_delete", {"shop": shop_id, "project": pid, "render": rid})
    c.commit()
    return {"ok": True}


class EditRIn(BaseModel):
    file_ids: list[int]
    task: str
    models: list[str] = ["gpt"]
    zones: dict[str, list[float]] = {}


@router.post("/api/shops/{shop_id}/visual/{pid}/render/edit")
def vis_render_edit(shop_id: int, pid: int, body: EditRIn, u=Depends(current_user), c=Depends(conn)):
    from . import visual_render as vr
    s = _shop(c, u, shop_id, "editor")
    _err(visual.project, c, shop_id, pid)
    batch = _rerr(vr.edit, c, shop_id, pid, u["id"], body.file_ids[:40], body.task, body.models, body.zones)
    _audit(c, u, s["workspace_id"], "visual/edit", {"shop": shop_id, "project": pid, "files": body.file_ids[:40], "task": body.task[:300],
                                                    "zones": body.zones})
    c.commit()
    vr.kick()
    return {"batch": batch}


class PhotoIn(BaseModel):
    file_ids: list[int]
    shared: bool = False


@router.post("/api/shops/{shop_id}/visual/{pid}/photos")
def vis_photo_add(shop_id: int, pid: int, body: PhotoIn, u=Depends(current_user), c=Depends(conn)):
    from . import visual_render as vr
    _shop(c, u, shop_id, "editor")
    for fid in body.file_ids[:60]:
        _rerr(vr.approve, c, shop_id, pid, fid, u["id"], body.shared)
    c.commit()
    return {"ok": True}


@router.delete("/api/shops/{shop_id}/visual_photo/{phid}")
def vis_photo_del(shop_id: int, phid: int, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "editor")
    c.execute("DELETE FROM vis_photos WHERE id=%s AND account_id=%s", (phid, shop_id))
    c.commit()
    return {"ok": True}


@router.get("/api/shops/{shop_id}/visual_shared")
def vis_shared(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    from . import visual_render as vr
    _shop(c, u, shop_id, "viewer")
    return jsonable_encoder({"rows": vr.photos(c, shop_id, None)})


class CardIn(BaseModel):
    file_ids: list[int]
    first: bool = False
    nm_id: int | None = None


@router.post("/api/shops/{shop_id}/visual/{pid}/to_card")
def vis_to_card(shop_id: int, pid: int, body: CardIn, u=Depends(current_user), c=Depends(conn)):
    """Фото — в черновик карточки WB (в начало или в конец). В WB уходит только кнопкой «Применить» в «Карточках»."""
    from . import actions, visual_render as vr
    s = _shop(c, u, shop_id, "editor")
    p = _err(visual.project, c, shop_id, pid)
    nm = body.nm_id or p["nm_id"]
    if not nm:
        raise HTTPException(400, "У товара нет артикула WB — укажите, в какую карточку")
    try:
        n = vr.to_card(c, shop_id, nm, body.file_ids[:30], u["id"], body.first)
    except (vr.RenderError, actions.ActionDenied) as e:
        raise HTTPException(400, str(e)) from None
    _audit(c, u, s["workspace_id"], "visual/to_card", {"shop": shop_id, "project": pid, "nm": nm, "files": body.file_ids[:30]})
    c.commit()
    return {"added": n, "nm_id": nm}


@router.get("/api/shops/{shop_id}/cards/{nm}/vis_photos")
def card_vis_photos(shop_id: int, nm: int, u=Depends(current_user), c=Depends(conn)):
    """«Карточки» → «＋ из базы фото»: одобренные фото визуала по этому артикулу и общие фото магазина."""
    from . import visual_render as vr
    _shop(c, u, shop_id, "viewer")
    return jsonable_encoder({"photos": vr.card_photos(c, shop_id, nm)})


@router.post("/api/shops/{shop_id}/cards/{nm}/from_visual")
def card_from_visual(shop_id: int, nm: int, body: PhotoIn, u=Depends(current_user), c=Depends(conn)):
    """Фото из «Базы фото» → в черновик карточки (порядок и «Применить» — в «Карточках»)."""
    from . import actions, visual_render as vr
    _shop(c, u, shop_id, "editor")
    ok = {r["file_id"] for r in vr.card_photos(c, shop_id, nm)}
    try:
        media = vr.card_media(c, shop_id, nm, [f for f in body.file_ids[:30] if f in ok], u["id"])
    except actions.ActionDenied as e:
        raise HTTPException(400, str(e)) from None
    c.commit()
    return {"media": media}



@router.get("/api/workspaces/{ws_id}/higgsfield")
def hf_status(ws_id: int, u=Depends(current_user), c=Depends(conn)):
    if not auth.can(auth.workspace_role(c, u, ws_id), "viewer"):
        raise HTTPException(403, "Нет доступа к кабинету")
    r = c.execute("""SELECT s.added_at, s.info, coalesce(x.name, x.email) who FROM workspace_secrets s LEFT JOIN users x ON x.id=s.added_by
                     WHERE s.workspace_id=%s AND s.kind='higgsfield'""", (ws_id,)).fetchone()
    return jsonable_encoder({"connected": bool(r), "added_at": r and r["added_at"], "who": r and r["who"], "email": r and (r["info"] or {}).get("email"),
                             "can_edit": auth.can(auth.workspace_role(c, u, ws_id), "admin")})


@router.post("/api/workspaces/{ws_id}/higgsfield/connect")
def hf_connect(ws_id: int, u=Depends(current_user), c=Depends(conn)):
    from . import higgsfield
    if not auth.can(auth.workspace_role(c, u, ws_id), "admin"):
        raise HTTPException(403, "Подключает админ или владелец кабинета")
    url = higgsfield.auth_url(c, ws_id, u["id"])
    c.commit()
    return {"url": url}


@router.get("/api/higgsfield/callback")
def hf_callback(state: str = "", code: str = "", error: str = "", c=Depends(conn)):
    from fastapi.responses import RedirectResponse
    from . import higgsfield
    if error or not code:
        return RedirectResponse("/?hf=error", status_code=302)
    try:
        ws = higgsfield.callback(c, state, code)
    except higgsfield.HFError:
        c.rollback()
        return RedirectResponse("/?hf=error", status_code=302)
    c.execute("INSERT INTO audit_log(user_id,workspace_id,action,details) SELECT added_by, workspace_id, 'higgsfield/connect', '{}' "
              "FROM workspace_secrets WHERE workspace_id=%s AND kind='higgsfield'", (ws,))
    c.commit()
    return RedirectResponse("/?hf=ok", status_code=302)


@router.delete("/api/workspaces/{ws_id}/higgsfield")
def hf_disconnect(ws_id: int, u=Depends(current_user), c=Depends(conn)):
    if not auth.can(auth.workspace_role(c, u, ws_id), "admin"):
        raise HTTPException(403, "Отключает админ или владелец кабинета")
    c.execute("DELETE FROM workspace_secrets WHERE workspace_id=%s AND kind='higgsfield'", (ws_id,))
    _audit(c, u, ws_id, "higgsfield/remove", {})
    c.commit()
    return {"ok": True}


@router.on_event("startup")
def _resume_renders():
    """После перезапуска сайта — дорисовать незавершённое (картинки, отправленные в Higgsfield до перезапуска)."""
    import threading
    from . import db, visual_render as vr

    def go():
        try:                                   
            visual_ai.resume_all()
        except Exception:  
            pass
        with db.connect() as c:
            q = c.execute("SELECT 1 FROM vis_renders WHERE state='queued' LIMIT 1").fetchone()   
        if q:                                                                                       
            vr.kick()
    threading.Thread(target=go, daemon=True).start()
