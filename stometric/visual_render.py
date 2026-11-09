"""Self-hosted application component."""

import json
import threading
import time
import uuid
from pathlib import Path

import httpx

from . import auth, db, higgsfield as hf, openai_images as oi, private_image_actor, vip_image as vip, visual

MODELS = {**{k: {**v, "title": v["title"] + " · Higgsfield", "provider": "higgsfield"} for k, v in hf.MODELS.items()},
          oi.MODEL_ID: {"title": oi.TITLE, "provider": "openai", "model": oi.MODEL},
          vip.MODEL_ID: {"title": vip.TITLE, "provider": "chatgpt"}}

KEEP = ("Use the attached product photos as the exact reference of the product. Do NOT change the product: its shape, color, proportions, "
        "materials, logos, labels, packaging/box and included parts must stay exactly as in the reference photos. You may change background, "
        "lighting, environment and add decorative elements around the product. Vertical 3:4 marketplace card slide. Keep all four corners free of "
        "text and important details. All visible text must be in Russian exactly as quoted, with correct spelling; no other text. "
        "Show ONLY this exact product from the reference photos: never draw any other product, bottle, package, logo or brand name, "
        "and never invent a different version of the product.")
EDIT = ("Edit the FIRST attached image: {task}. Keep everything else in it as is unless the task says otherwise. The other attached images (if any) "
        "show the real product - the product must stay exactly the same (shape, color, proportions, logos, packaging). Vertical 3:4. "
        "Any visible text must be in Russian with correct spelling.")
ZONE = (" IMPORTANT: change ONLY the area marked with the red frame on the SECOND attached image (it is the same picture with the frame drawn on it; "
        "the area is about {x}%..{x2}% from the left and {y}%..{y2}% from the top). Do NOT draw the red frame. Everything outside this area must "
        "stay exactly as in the first image: same composition, size and position of all elements. Any new object must fit COMPLETELY inside "
        "the marked area with a small margin (scale it down if needed - never cut it by the frame edge) and match the slide's lighting, "
        "perspective and style.")
POLL_S = 6
MAX_WAIT_S = 15 * 60
PARALLEL = 3
_LOCK = threading.Lock()
_WORKER: list[threading.Thread] = []


class RenderError(RuntimeError):
    pass


NO_HF = "Аккаунт Higgsfield не подключён — Настройки аккаунта → «Higgsfield»"


def _vip_editor(c, shop: int, uid: int | None) -> bool:
    return private_image_actor.allowed(c, shop, uid) and auth.can(auth.shop_role(c, {"id": uid}, shop), "editor")


PAID_GPT_MODELS = frozenset((oi.MODEL_ID, "gpt", "sunburst"))
VIP_GPT_ONLY = "Для этого VIP-магазина выберите GPT Image по личной подписке ChatGPT."
VIP_DENIED = "Личная подписка ChatGPT доступна владельцу в выбранных личных магазинах."
VIP_UNAVAILABLE = "Источник отрисовки по личной подписке ChatGPT сейчас недоступен."


def models(c, shop: int, uid: int | None = None) -> list[dict]:
    personal = _vip_editor(c, shop, uid)
    hf_ok = hf.connected(c, shop)
    api_ok = False if personal else oi.connected(c, shop)
    options = []
    if personal:
        ready = vip.available(c, shop)
        options.append({"id": vip.MODEL_ID, **MODELS[vip.MODEL_ID], "ready": ready,
                        "why": None if ready else VIP_UNAVAILABLE, "default": ready})
    for model_id, model in MODELS.items():
        if model_id == vip.MODEL_ID or (personal and model_id in PAID_GPT_MODELS):
            continue
        ready, why = (api_ok, oi.NO_KEY) if model_id == oi.MODEL_ID else (hf_ok, NO_HF)
        options.append({"id": model_id, "title": model["title"], "provider": model["provider"],
                        "ready": ready, "why": None if ready else why})
    return options


def selected(c, shop: int, mods: list[str], uid: int | None = None) -> list[str]:
    if not mods or any(m not in MODELS for m in mods):
        raise RenderError("Выберите доступную нейросеть")
    mods = list(dict.fromkeys(mods))
    personal = _vip_editor(c, shop, uid)
    if personal and PAID_GPT_MODELS.intersection(mods):
        raise RenderError(VIP_GPT_ONLY)
    if vip.MODEL_ID in mods:
        if not personal:
            raise RenderError(VIP_DENIED)
        if not vip.available(c, shop):
            raise RenderError(VIP_UNAVAILABLE)
    if oi.MODEL_ID in mods and not oi.connected(c, shop):
        raise RenderError(oi.NO_KEY)
    if any(m in hf.MODELS for m in mods) and not hf.connected(c, shop):
        raise RenderError(NO_HF)
    return mods


def plan(c, shop: int, pid: int) -> dict:
    """Что можно нарисовать по последнему ТЗ: варианты первого слайда и слайды."""
    b = visual.brief_latest(c, pid)
    if not b:
        return {"brief": None, "items": []}
    d = b["data"] or {}
    items = [{"slot": f"first:{i + 1}", "title": f"Слайд 1 — вариант {f.get('variant') or i + 1}: {f.get('style') or ''}".strip(),
              "prompt": f.get("prompt") or "", "sources": f.get("sources") or []} for i, f in enumerate(d.get("first_slides") or [])]
    items += [{"slot": f"slide:{i + 2}", "title": f"Слайд {i + 2}: {s.get('goal') or ''}", "prompt": s.get("prompt") or "",
               "sources": s.get("sources") or []} for i, s in enumerate(d.get("slides") or [])]
    return {"brief": {"id": b["id"], "version": b["version"], "state": b["state"]}, "items": items}


def _refs(c, pid: int, wanted: list) -> list[int]:
    own = [r["id"] for r in c.execute("SELECT id FROM vis_files WHERE project_id=%s AND kind='source' ORDER BY id", (pid,))]
    ids = [int(x) for x in wanted if str(x).isdigit() and int(x) in own]
    return (ids or own[:3])[:6]


def estimate(c, shop: int, n_by_model: dict[str, int], uid: int | None = None) -> dict:
    """Separate billing units; unknown OpenAI cost must never look like zero credits."""
    selected(c, shop, list(n_by_model), uid)
    cl = hf.Client(c, shop) if any(m in hf.MODELS for m in n_by_model) else None
    out, total, unknown = {}, 0.0, False
    for m, n in n_by_model.items():
        if not 1 <= n <= 60:
            raise RenderError("За один раз — от 1 до 60 картинок")
        if m == vip.MODEL_ID:
            unit, note, one = "subscription", vip.BILLING, None
        elif m == oi.MODEL_ID:
            unit, note, one = "USD", oi.BILLING, None
        else:
            unit, note, one = "credits", "Кредиты Higgsfield", hf.cost(cl, m)
        out[m] = {"title": MODELS[m]["title"], "one": one, "n": n, "sum": round(one * n, 2) if one is not None else None,
                  "unit": unit, "note": note}
        unknown = unknown or one is None
        total += (one or 0) * n
    return {"by_model": out, "total": None if unknown else round(total, 2)}


NO_SRC = ("Нет фото нашего товара: рисуем только по фото своих карточек . Добавьте исходники — «Фото с карточки» "
          "или загрузите свои — во вкладке «0. Исходники и паспорт»")


def own_sources(c, shop: int, pid: int) -> int:
    """Сколько своих исходников у проекта; нет — пробуем взять фото своей карточки с маркетплейса."""
    n = c.execute("SELECT count(*) n FROM vis_files WHERE project_id=%s AND account_id=%s AND kind='source'", (pid, shop)).fetchone()["n"]
    if not n:
        n = visual.ensure_sources(c, shop, pid, None)
        c.commit()
    return n


def start(c, shop: int, pid: int, uid: int, picks: list[dict], mods: list[str], per: int) -> str:
    """Нарисовать выбранные слоты ТЗ выбранными моделями, per вариантов на слот. Только по согласованному ТЗ и только с фото нашего товара."""
    visual.project(c, shop, pid)
    mods = selected(c, shop, mods, uid)
    if not own_sources(c, shop, pid):
        raise RenderError(NO_SRC)
    pl = plan(c, shop, pid)
    if not pl["brief"]:
        raise RenderError("Сначала соберите ТЗ")
    if pl["brief"]["state"] != "approved":
        raise RenderError("Рисуем по согласованному ТЗ — отправьте ТЗ на согласование менеджеру")
    by = {x["slot"]: x for x in pl["items"]}
    slots = [p for p in picks if p in by]
    if not slots:
        raise RenderError("Выберите слайды")
    if len(slots) * len(mods) * per > 60:
        raise RenderError("За один раз — не больше 60 картинок")
    batch = uuid.uuid4().hex[:12]
    for s in slots:
        it = by[s]
        refs = _refs(c, pid, it["sources"])
        for m in mods:
            for _ in range(per):
                c.execute("""INSERT INTO vis_renders(account_id,project_id,brief_id,batch,slot,title,model,prompt,refs,idem,created_by)
                             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                          (shop, pid, pl["brief"]["id"], batch, s, it["title"][:300], m, f"{it['prompt']}\n\n{KEEP}", refs, str(uuid.uuid4()), uid))
    return batch


def approve_brief(c, pid: int, uid: int, note: str) -> dict:
    """«Отправить в отрисовку» / «Все шаги + отрисовка»: последнее ТЗ считается согласованным нажавшим."""
    b = visual.brief_latest(c, pid)
    if not b:
        raise RenderError("Сначала соберите ТЗ")
    if b["state"] != "approved":
        c.execute("UPDATE vis_briefs SET state='approved', review_comment=%s, reviewed_by=%s, reviewed_at=now(), updated_at=now() WHERE id=%s",
                  (note, uid, b["id"]))
    return b


def auto(c, shop: int, pid: int, uid: int, mods: list[str], scope: str) -> int:
    """Согласовать последнее ТЗ и поставить в очередь все слайды (scope=all) или только варианты первого (first), по 1 на модель."""
    visual.project(c, shop, pid)
    selected(c, shop, mods, uid)
    approve_brief(c, pid, uid, "согласовано автоматически: «Все шаги + отрисовка»")
    items = plan(c, shop, pid)["items"]
    slots = [x["slot"] for x in items if scope != "first" or x["slot"].startswith("first:")]
    start(c, shop, pid, uid, slots, mods, 1)
    return len(slots) * len(set(mods))


def _zone(z) -> list[float] | None:
    """Область [x, y, w, h] в долях картинки (0..1); слишком маленькая или вся картинка — без области."""
    try:
        x, y, w, h = (min(max(float(v), 0.0), 1.0) for v in z[:4])
    except (TypeError, ValueError):
        return None
    w, h = min(w, 1 - x), min(h, 1 - y)
    return [round(x, 4), round(y, 4), round(w, 4), round(h, 4)] if w >= 0.02 and h >= 0.02 and w * h < 0.95 else None


def edit(c, shop: int, pid: int, uid: int, file_ids: list[int], task: str, mods: list[str], zones: dict | None = None) -> str:
    """Доработать выбранные фото (слайды, исходники, из базы) по заданию: каждое перерисовывается от себя, товар — по исходникам.
    zones {file_id: [x, y, w, h]} — менять только выделенную область (нейросети — копия с красной рамкой, вне области — оригинал)."""
    task = (task or "").strip()
    if not task:
        raise RenderError("Напишите, что сделать с фото")
    visual.project(c, shop, pid)
    mods = selected(c, shop, mods, uid)
    ok = [r["id"] for r in c.execute("SELECT id FROM vis_files WHERE account_id=%s AND id = ANY(%s) AND kind IN ('source','render')", (shop, file_ids))]
    if vip.MODEL_ID in mods and set(ok) != set(file_ids):
        raise RenderError("Исходное фото недоступно в этом магазине")
    if not ok:
        raise RenderError("Выберите фото")
    if len(ok) * len(mods) > 40:
        raise RenderError("За один раз — не больше 40 картинок")
    if pid and not own_sources(c, shop, pid):
        raise RenderError(NO_SRC)
    batch = uuid.uuid4().hex[:12]
    src = [x for x in _refs(c, pid, []) if x not in ok][:3] if pid else []
    for fid in ok:
        par = c.execute("SELECT id, slot, title FROM vis_renders WHERE file_id=%s", (fid,)).fetchone()
        z = _zone((zones or {}).get(str(fid)) or (zones or {}).get(fid))
        prompt = EDIT.format(task=task[:1500])
        if z:
            prompt += ZONE.format(x=round(z[0] * 100), x2=round((z[0] + z[2]) * 100), y=round(z[1] * 100), y2=round((z[1] + z[3]) * 100))
        for m in mods:
            c.execute("""INSERT INTO vis_renders(account_id,project_id,batch,slot,title,model,prompt,refs,parent_id,task,idem,created_by,zone)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                      (shop, pid, batch, par["slot"] if par else "edit", ((par["title"] if par else "Доработка") + " · доработка")[:300], m,
                       prompt, [fid, *src], par["id"] if par else None, task[:2000], str(uuid.uuid4()), uid, json.dumps(z) if z else None))
    return batch



def kick():
    """Запустить обработчик очереди, если он ещё не работает (в этом процессе)."""
    with _LOCK:
        if _WORKER and _WORKER[0].is_alive():
            return
        t = threading.Thread(target=_loop, daemon=True)
        _WORKER[:] = [t]
        t.start()


def _loop():
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(PARALLEL) as ex:
        while True:
            with db.connect() as c:
                rows = _claim(c)
                c.commit()
            if not rows:
                return
            list(ex.map(_one, [r["id"] for r in rows]))


def _expire_direct(c, pid: int | None = None):
    c.execute("""UPDATE vis_renders SET state='error',
                 error=CASE WHEN model=%s THEN %s ELSE %s END, finished_at=now()
                 WHERE model IN (%s,%s) AND state='running'
                   AND coalesce(started_at,created_at) < now() - interval '25 minutes'"""
              + (" AND project_id=%s" if pid is not None else ""),
              (vip.MODEL_ID, vip.UNCERTAIN, oi.UNCERTAIN, vip.MODEL_ID, oi.MODEL_ID)
              + ((pid,) if pid is not None else ()))


def _claim(c):
    
    
    c.execute("SELECT pg_advisory_xact_lock(hashtext('seller-analytics:visual:render-claim'))")
    _expire_direct(c)
    return c.execute("""UPDATE vis_renders SET state='running', started_at=now() WHERE id IN (
        SELECT id FROM vis_renders WHERE state='queued' AND (
            model NOT IN (%(api)s,%(vip)s) OR (id=(SELECT min(id) FROM vis_renders WHERE state='queued' AND model IN (%(api)s,%(vip)s))
                AND NOT EXISTS (SELECT 1 FROM vis_renders WHERE state='running' AND model IN (%(api)s,%(vip)s))))
        ORDER BY id LIMIT %(n)s FOR UPDATE SKIP LOCKED) RETURNING id""", {"api":oi.MODEL_ID, "vip":vip.MODEL_ID, "n":PARALLEL}).fetchall()


def _direct_refs(c, r: dict) -> list[bytes]:
    if not r["refs"]:
        raise RenderError(NO_SRC)
    refs, total = [], 0
    root = (visual.DIR / str(r["account_id"])).resolve()
    for fid in r["refs"]:
        f = c.execute("SELECT path FROM vis_files WHERE id=%s AND account_id=%s AND kind IN ('source','render')",
                      (fid, r["account_id"])).fetchone()
        if not f:
            raise RenderError("Исходное фото недоступно в этом магазине")
        path = Path(f["path"])
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise RenderError("Файл исходного фото недоступен")
        with path.open("rb") as fh:
            raw = fh.read(oi.MAX_IMAGE + 1)
        oi.validate_image(raw)
        total += len(raw)
        if total > 60 * 1024 * 1024:
            raise RenderError("Исходники суммарно больше 60 МБ")
        refs.append(raw)
    if r.get("zone"):
        refs.insert(1, _framed(refs[0], r["zone"]))
    return refs


def _direct_authorize(c, r: dict):
    u = c.execute("SELECT id, is_active, is_superadmin FROM users WHERE id=%s", (r["created_by"],)).fetchone()
    if not u or not auth.can(auth.shop_role(c, u, r["account_id"]), "editor"):
        raise RenderError("Доступ автора к отрисовке этого магазина отозван")
    if r.get("model") == vip.MODEL_ID and not private_image_actor.allowed(c, r["account_id"], r["created_by"]):
        raise RenderError(VIP_DENIED)
    p = visual.project(c, r["account_id"], r["project_id"])
    if p.get("archived"):
        raise RenderError("Проект архивирован")


def _direct_one(c, r: dict):
    rid = r["id"]
    subscription = r["model"] == vip.MODEL_ID
    provider = vip if subscription else oi
    try:
        _direct_authorize(c, r)
        if subscription and not vip.available(c, r["account_id"]):
            raise RenderError(VIP_UNAVAILABLE)
        token = None if subscription else oi.key(c, r["account_id"])
        refs = _direct_refs(c, r)
        
        
        claimed = c.execute("""UPDATE vis_renders SET request_id=%s WHERE id=%s AND state='running'
                               AND request_id IS NULL RETURNING id""", ("chatgpt:started" if subscription else "openai:started", rid)).fetchone()
        c.commit()
        if not claimed:
            return
        if subscription:
            raw = vip.generate(r["prompt"], refs, r["created_by"], shop=r["account_id"])
        else:
            raw = oi.generate(token, r["prompt"], refs, r["created_by"])
        token = None
        _direct_authorize(c, r)
        state = c.execute("SELECT state FROM vis_renders WHERE id=%s FOR UPDATE", (rid,)).fetchone()
        if not state or state["state"] != "running":
            c.commit()
            return
        if r.get("zone"):
            raw = _paste_exact(refs[0], raw, r["zone"])
        ext = ".jpg" if subscription and oi.validate_image(raw) == "image/jpeg" else ".png"
        f = visual.save(c, r["account_id"], r["project_id"], "render", f"{r['title'][:80]} · {provider.TITLE}{ext}",
                        raw, r["created_by"], vip.MODEL_ID if subscription else oi.MODEL)
        c.execute("UPDATE vis_renders SET state='done', file_id=%s, finished_at=now() WHERE id=%s", (f["id"], rid))
        c.commit()
        del refs, raw, token  
    except Exception as exc:
        c.rollback()
        msg = str(exc) if isinstance(exc, (RenderError, oi.ImageError)) else provider.UNCERTAIN
        c.execute("""UPDATE vis_renders SET state='error', error=%s, finished_at=now()
                     WHERE id=%s AND state='running'""", (msg[:400], rid))
        c.commit()
        return
    try:
        check(rid)
    except Exception:
        
        
        c.rollback()
        c.execute("""UPDATE vis_renders SET check_res='{"skipped":true}'::jsonb
                     WHERE id=%s AND state='done' AND check_res IS NULL""", (rid,))
        c.commit()


def _one(rid: int):
    with db.connect() as c:
        r = c.execute("SELECT * FROM vis_renders WHERE id=%s", (rid,)).fetchone()
        if not r or r["state"] != "running":
            return
        if r["model"] in (oi.MODEL_ID, vip.MODEL_ID):
            c.commit()
            _direct_one(c, r)
            return
        try:
            if not r["refs"]:                       
                raise RenderError(NO_SRC)
            cl = hf.Client(c, r["account_id"])
            if not r["request_id"]:
                mids = []
                for fid in r["refs"] or []:
                    f = c.execute("SELECT path, mime, name FROM vis_files WHERE id=%s", (fid,)).fetchone()
                    if f and Path(f["path"]).exists():
                        raw, mime = Path(f["path"]).read_bytes(), f["mime"]
                        if mime == "image/webp":                       
                            raw, mime = _jpeg(raw), "image/jpeg"
                        mids.append(hf.upload(cl, raw, mime, f"ref_{fid}{'.png' if mime == 'image/png' else '.jpg'}"))
                        if r.get("zone") and len(mids) == 1:      
                            mids.append(hf.upload(cl, _framed(raw, r["zone"]), "image/jpeg", f"zone_{fid}.jpg"))
                req = hf.submit(cl, r["model"], r["prompt"], mids)
                c.execute("UPDATE vis_renders SET request_id=%s WHERE id=%s", (req, rid))
                c.commit()
                r = {**r, "request_id": req}
            t0 = time.time()
            while True:
                if c.execute("SELECT state FROM vis_renders WHERE id=%s", (rid,)).fetchone()["state"] == "canceled":
                    c.commit()
                    return                          
                c.commit()
                st = hf.wait(cl, r["request_id"])
                if st.get("status") == "completed":
                    break
                if st.get("status") in ("failed", "nsfw", "canceled", "error"):
                    raise RenderError({"nsfw": "Нейросеть отклонила картинку модерацией", "canceled": "Отменено"}.get(st["status"])
                                      or f"Нейросеть не справилась: {st.get('error') or 'ошибка'}")
                if time.time() - t0 > MAX_WAIT_S:
                    raise RenderError("Нейросеть не успела за 15 минут — попробуйте ещё раз")
                time.sleep(2)
            img = st.get("result_url") or ((st.get("results") or [{}])[0] or {}).get("url")
            if not img:
                raise RenderError("Нейросеть не вернула картинку")
            raw = httpx.get(img, timeout=120).content
            if r.get("zone") and r["refs"]:          
                f0 = c.execute("SELECT path FROM vis_files WHERE id=%s", (r["refs"][0],)).fetchone()
                if f0 and Path(f0["path"]).exists():
                    raw = _paste(Path(f0["path"]).read_bytes(), raw, r["zone"])
            ext = ".png" if raw[:4] == b"\x89PNG" else ".webp" if raw[8:12] == b"WEBP" else ".jpg"
            f = visual.save(c, r["account_id"], r["project_id"], "render", f"{r['title'][:80]} · {hf.MODELS.get(r['model'], {}).get('title', r['model'])}{ext}",
                            raw, r["created_by"], f"{r['model']} {r['request_id']}")
            c.execute("UPDATE vis_renders SET state='done', file_id=%s, finished_at=now() WHERE id=%s AND state<>'canceled'", (f["id"], rid))
            c.commit()
        except Exception as e:  
            c.rollback()
            msg = str(e)[:400] if isinstance(e, (RenderError, hf.HFError, visual.VisualError)) else f"{type(e).__name__}: {str(e)[:300]}"
            c.execute("UPDATE vis_renders SET state='error', error=%s, finished_at=now() WHERE id=%s AND state<>'canceled'", (msg, rid))
            c.commit()
            return
    try:
        check(rid)
    except Exception:  
        pass


def _paste_exact(orig: bytes, generated: bytes, z: list[float]) -> bytes:
    """Direct OpenAI region edits: preserve pixels outside selection, output PNG."""
    import io
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(orig)) as a, Image.open(io.BytesIO(generated)) as b:
        a = a.convert("RGBA")
        b = ImageOps.fit(b.convert("RGBA"), a.size, method=Image.Resampling.LANCZOS)
        box = (round(z[0] * a.width), round(z[1] * a.height),
               round((z[0] + z[2]) * a.width), round((z[1] + z[3]) * a.height))
        a.paste(b.crop(box), box[:2])
        out = io.BytesIO()
        a.save(out, "PNG")
        return out.getvalue()


def _framed(raw: bytes, z: list[float]) -> bytes:
    """Копия картинки с красной рамкой вокруг области — так нейросеть видит, что менять."""
    import io
    from PIL import Image, ImageDraw
    with Image.open(io.BytesIO(raw)) as im:
        im = im.convert("RGB")
        W, H = im.size
        t = max(3, round(min(W, H) * 0.008))
        ImageDraw.Draw(im).rectangle([z[0] * W, z[1] * H, (z[0] + z[2]) * W, (z[1] + z[3]) * H], outline=(255, 0, 0), width=t)
        b = io.BytesIO()
        im.save(b, "JPEG", quality=92)
        return b.getvalue()


def _paste(orig: bytes, new: bytes, z: list[float]) -> bytes:
    """Результат нейросети приводим к размеру оригинала и берём из него только область (с мягким краем), остальное — оригинал."""
    import io
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    with Image.open(io.BytesIO(orig)) as a, Image.open(io.BytesIO(new)) as b:
        a, b = a.convert("RGB"), b.convert("RGB")
        W, H = a.size
        if abs(b.width / b.height - W / H) > 0.01:          
            if b.width / b.height > W / H:
                nw = round(b.height * W / H)
                b = b.crop(((b.width - nw) // 2, 0, (b.width - nw) // 2 + nw, b.height))
            else:
                nh = round(b.width * H / W)
                b = b.crop((0, (b.height - nh) // 2, b.width, (b.height - nh) // 2 + nh))
        b = b.resize((W, H), Image.LANCZOS)
        pad = max(4, round(min(W, H) * 0.015))
        x0, y0, x1, y1 = z[0] * W, z[1] * H, (z[0] + z[2]) * W, (z[1] + z[3]) * H
        m = Image.new("L", (W, H), 0)
        ImageDraw.Draw(m).rectangle([x0 - pad, y0 - pad, x1 + pad, y1 + pad], fill=255)
        
        gx, gy = (x1 - x0) * 0.5, (y1 - y0) * 0.5
        box = (max(0, round(x0 - gx)), max(0, round(y0 - gy)), min(W, round(x1 + gx)), min(H, round(y1 + gy)))
        d = ImageChops.difference(a.crop(box).filter(ImageFilter.GaussianBlur(2)), b.crop(box).filter(ImageFilter.GaussianBlur(2))).convert("L")
        d = d.point(lambda v: 255 if v > 40 else 0).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(_odd(min(W, H) * 0.02)))
        near = Image.new("L", (W, H), 0)
        near.paste(d, box[:2])
        m = ImageChops.lighter(m, near).filter(ImageFilter.GaussianBlur(pad))
        a.paste(b, (0, 0), m)
        out = io.BytesIO()
        a.save(out, "JPEG", quality=94)
        return out.getvalue()


def _odd(v: float) -> int:
    n = max(3, int(v))
    return n if n % 2 else n + 1


def _jpeg(raw: bytes) -> bytes:
    import io
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as im:
        b = io.BytesIO()
        im.convert("RGB").save(b, "JPEG", quality=92)
        return b.getvalue()


def check(rid: int):
    """ИИ сравнивает готовую картинку с исходниками: товар тот же? русский текст без ошибок? Результат — подсказка в галерее."""
    from . import visual_ai
    with db.connect() as c:
        r = c.execute("SELECT * FROM vis_renders WHERE id=%s", (rid,)).fetchone()
        if not r or not r["file_id"]:
            return
        if r["model"] == vip.MODEL_ID:
            _direct_authorize(c, r)
            c._ai_actor_id = r["created_by"]
        key = visual_ai._key(c, r["account_id"])
        files = [visual_ai.TMP / f"chk_{r['file_id']}.jpg"]
        visual_ai.TMP.mkdir(parents=True, exist_ok=True)
        files[0].write_bytes(visual.thumb(c, r["account_id"], r["file_id"], 1000))
        for fid in [x for x in r["refs"] or [] if x != r["file_id"]][:2]:
            p = visual_ai.TMP / f"chk_ref_{fid}.jpg"
            p.write_bytes(visual.thumb(c, r["account_id"], fid, 800))
            files.append(p)
        res = visual_ai._ask(key, "Первое вложение - сгенерированный слайд карточки товара, остальные - реальные фото товара. Проверь:\n"
                             "1) товар на слайде тот же, что на реальных фото (форма, цвет, пропорции, логотипы, упаковка, комплектация) - перечисли отличия;\n"
                             "2) весь русский текст на слайде: выпиши его и найди орфографические ошибки, искажённые буквы, бессмысленные слова;\n"
                             "3) нет ли значимого текста/деталей в углах.\n"
                             'JSON: {"product_ok": true/false, "product_diff": ["..."], "text": "весь текст на слайде", "text_ok": true/false, '
                             '"text_errors": ["..."], "corners_ok": true/false}', [str(x) for x in files], max_tokens=2000)
        c.execute("UPDATE vis_renders SET check_res=%s WHERE id=%s", (json.dumps(res, ensure_ascii=False), rid))
        c.commit()


def renders(c, pid: int) -> list[dict]:
    rows = c.execute("""SELECT id, batch, slot, title, model, state, error, file_id, check_res, parent_id, task, zone, created_at, finished_at
                        FROM vis_renders WHERE project_id=%s ORDER BY id DESC LIMIT 400""", (pid,)).fetchall()
    return [{**row, "model_title": MODELS.get(row["model"], {}).get("title", row["model"])} for row in rows]


def ensure_running(c, pid: int):
    
    
    _expire_direct(c, pid)
    c.commit()
    if c.execute("SELECT 1 FROM vis_renders WHERE project_id=%s AND state IN ('queued','running') LIMIT 1", (pid,)).fetchone():
        stale = c.execute("""UPDATE vis_renders SET state='queued' WHERE project_id=%s AND state='running'
                             AND model NOT IN (%s,%s) AND coalesce(started_at,created_at) < now() - interval '25 minutes' RETURNING id""", (pid, oi.MODEL_ID, vip.MODEL_ID)).fetchall() if not (_WORKER and _WORKER[0].is_alive()) else []
        if stale:
            c.commit()
        kick()




SLIDE_ORDER = """(SELECT CASE WHEN r.slot LIKE 'first:%%' THEN coalesce(substring(r.slot from '[0-9]+')::int, 0)
                                WHEN r.slot LIKE 'slide:%%' THEN 100 + coalesce(substring(r.slot from '[0-9]+')::int, 0) ELSE 999 END
                     FROM vis_renders r WHERE r.id = coalesce(ph.render_id, (SELECT id FROM vis_renders WHERE file_id=ph.file_id LIMIT 1)))"""


def photos(c, shop: int, pid: int | None) -> list[dict]:
    return c.execute(f"""SELECT ph.id, ph.file_id, ph.title, ph.project_id, ph.created_at, f.name FROM vis_photos ph JOIN vis_files f ON f.id=ph.file_id
                        WHERE ph.account_id=%s AND """ + ("ph.project_id=%s" if pid else "ph.project_id IS NULL") + f" ORDER BY coalesce({SLIDE_ORDER}, 999), ph.id",
                     (shop, pid) if pid else (shop,)).fetchall()


def approve(c, shop: int, pid: int | None, file_id: int, uid: int, shared: bool, title: str = "") -> None:
    f = c.execute("SELECT id, name FROM vis_files WHERE id=%s AND account_id=%s AND kind IN ('render','source')", (file_id, shop)).fetchone()
    if not f:
        raise RenderError("Нет такого фото")
    rid = (c.execute("SELECT id FROM vis_renders WHERE file_id=%s", (file_id,)).fetchone() or {}).get("id")
    c.execute("""INSERT INTO vis_photos(account_id,project_id,file_id,render_id,title,created_by) VALUES (%s,%s,%s,%s,%s,%s)
                 ON CONFLICT DO NOTHING""", (shop, None if shared else pid, file_id, rid, (title or f["name"])[:200], uid))


def to_card(c, shop: int, nm: int, file_ids: list[int], uid: int, first: bool) -> int:
    """Добавить фото в черновик карточки (в конец или в начало). В WB уходит только кнопкой «Применить» в «Карточках»."""
    from . import cards
    d = cards.draft_open(c, shop, nm, uid)
    cur = d["changes"].get("media") or cards.view(d["base"])["media"]
    new = card_media(c, shop, nm, file_ids, uid)
    if not new:
        raise RenderError("Выберите фото")
    if len(cur) + len(new) > 30:
        raise RenderError(f"В карточке WB до 30 фото, а получится {len(cur) + len(new)} — уберите лишние в «Карточках»")
    photos_ = [m for m in cur if m["kind"] == "photo"]
    video = [m for m in cur if m["kind"] != "photo"]
    cards.draft_set(c, shop, nm, "media", (new + photos_ if first else photos_ + new) + video, uid, source="visual")
    return len(new)


def card_photos(c, shop: int, nm: int) -> list[dict]:
    """«База фото» для «Карточек»: одобренные фото проектов этого артикула и «Общие фото» магазина."""
    return c.execute(f"""SELECT ph.file_id, ph.title, ph.project_id, p.title project, ph.created_at FROM vis_photos ph
                        LEFT JOIN vis_projects p ON p.id=ph.project_id
                        WHERE ph.account_id=%s AND (ph.project_id IS NULL OR p.nm_id=%s)
                        ORDER BY ph.project_id IS NULL, ph.project_id DESC, coalesce({SLIDE_ORDER}, 999), ph.id""",
                     (shop, nm)).fetchall()


def card_media(c, shop: int, nm: int, file_ids: list[int], uid: int) -> list[dict]:
    """Фото визуала → загрузки черновика карточки (ссылки, которые WB заберёт при «Применить»)."""
    from . import cards
    new = []
    for fid in file_ids:
        f = c.execute("SELECT path, name, mime FROM vis_files WHERE id=%s AND account_id=%s", (fid, shop)).fetchone()
        if not f:
            continue
        raw = Path(f["path"]).read_bytes()
        name = f["name"]
        if f["mime"] == "image/webp":
            raw, name = _jpeg(raw), Path(name).stem + ".jpg"
        elif not Path(name).suffix:
            name += {"image/png": ".png"}.get(f["mime"], ".jpg")
        new.append(cards.save_upload(c, shop, nm, name, raw, uid))
    return new


def stop(c, shop: int, pid: int) -> int:
    """Остановить отрисовку проекта: очередь и идущие — «отменено» (уже начатые у Higgsfield кредиты могут списаться)."""
    n = c.execute("""UPDATE vis_renders SET state='canceled', error='остановлено', finished_at=now()
                     WHERE account_id=%s AND project_id=%s AND state IN ('queued','running')""", (shop, pid)).rowcount
    return n


def delete(c, shop: int, pid: int, rid: int) -> bool:
    """Self-hosted application component."""
    r = c.execute("SELECT id, file_id, state FROM vis_renders WHERE id=%s AND account_id=%s AND project_id=%s", (rid, shop, pid)).fetchone()
    if not r:
        raise RenderError("Нет такой картинки")
    if r["state"] in ("queued", "running"):
        raise RenderError("Картинка ещё рисуется — сначала остановите отрисовку")
    c.execute("DELETE FROM vis_renders WHERE id=%s", (rid,))
    if r["file_id"]:
        f = c.execute("DELETE FROM vis_files WHERE id=%s AND account_id=%s AND kind='render' RETURNING path", (r["file_id"], shop)).fetchone()
        if f and f["path"]:
            p = Path(f["path"])
            for x in [p, *p.parent.glob(f"{p.stem}_t*.jpg")]:
                x.unlink(missing_ok=True)
    return True
