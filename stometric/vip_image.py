"""Personal image adapter. Rights are checked before queueing and dispatch."""
import base64
import hashlib
import os
import stat
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID
from . import openai_images as images
from .owner_paths import PROFILE

MODEL_ID = 'vip_chatgpt_image'
TITLE = 'GPT Image · личная подписка ChatGPT'
BILLING = 'Лимиты личной подписки владельца; автоматического перехода на API нет.'
UNCERTAIN = 'Результат генерации не подтверждён. Лимит мог быть использован; автоматического повтора нет.'
LIMIT = 'Лимит личной подписки исчерпан. Повторите вручную после обновления лимита.'
RATE_LIMIT = 'Ограничение частоты запросов. Повторите позже вручную.'
CREDIT_STATE_UNKNOWN = 'Codex не подтвердил доступность работы только в пределах подписки. Запрос не отправлен.'
EXTRA_CREDITS = 'Дополнительные кредиты доступны: запрос остановлен, чтобы не расходовать их автоматически.'
ARTIFACTS = PROFILE / 'generated_images'


def available(c, shop):
    if c is None:
        return False
    from .owner_ai import settings
    cfg = settings(c)
    return bool(cfg.get('enabled') and shop in cfg.get('shop_ids', []) and cfg.get('image_ready'))


def generate(prompt, refs, uid, shop=None):
    from . import db, owner_ai, owner_runtime
    with db.connect() as c:
        key = owner_ai.key_for(c, shop, uid)
    if key is None:
        raise ImageError('Нет доступа к личной подписке для этого магазина.')
    return owner_runtime.generate_image(key, prompt, refs)

class ImageError(images.ImageError):
    pass

def prepare(prompt, refs, uid, folder):
    if type(uid) is not int or uid <= 0 or not isinstance(prompt, str) or not 0 < len(prompt.strip()) <= 32000:
        raise ImageError("Проверьте задание и пользователя.")
    if (not isinstance(refs, (list, tuple)) or not (1 <= len(refs) <= 16)
            or not all(isinstance(r, bytes) for r in refs) or sum(map(len, refs)) > 60 * 1024 * 1024):
        raise ImageError("Нужны фото товара: до 16 файлов, суммарно до 60 МБ.")
    expected = {}
    for index, raw in enumerate(refs):
        mime = images.validate_image(raw)
        path = folder / f"reference-{index+1}.{mime.split('/')[-1]}"
        with path.open("xb") as out:
            out.write(raw)
        expected[str(path)] = hashlib.sha256(raw).hexdigest()
    return expected

def check_limit(info):
    if info == "usageLimitExceeded":
        raise ImageError(LIMIT)
    if info == "rateLimitExceeded":
        raise ImageError(RATE_LIMIT)

def included_allowance(snapshot):
    # No per-turn billing cap exists for managed ChatGPT. Never submit when paid
    # fallback is available, when quota is depleted, or when either fact is unknown.
    if not isinstance(snapshot, dict) or not snapshot.get("accountId"):
        raise ImageError(CREDIT_STATE_UNKNOWN)
    if snapshot.get("ordinaryUsageAllowed") is False:
        raise ImageError(LIMIT)
    if snapshot.get("ordinaryUsageAllowed") is not True:
        raise ImageError(CREDIT_STATE_UNKNOWN)
    by_id = snapshot.get("rateLimitsByLimitId")
    if not isinstance(by_id, dict) or "codex" not in by_id:
        raise ImageError(CREDIT_STATE_UNKNOWN)
    for bucket in [snapshot.get("rateLimits"), *by_id.values()]:
        if not isinstance(bucket, dict):
            raise ImageError(CREDIT_STATE_UNKNOWN)
        if bucket.get("rateLimitReachedType") or bucket.get("spendControlReached") is True:
            raise ImageError(LIMIT)
        windows = [value for value in (bucket.get("primary"), bucket.get("secondary")) if value is not None]
        if not windows:
            raise ImageError(CREDIT_STATE_UNKNOWN)
        for window in windows:
            percent = window.get("usedPercent") if isinstance(window, dict) else None
            if type(percent) not in (int, float) or not 0 <= percent <= 100:
                raise ImageError(CREDIT_STATE_UNKNOWN)
            if percent == 100:
                raise ImageError(LIMIT)
        credits = bucket.get("credits")
        if not isinstance(credits, dict):
            raise ImageError(CREDIT_STATE_UNKNOWN)
        if credits.get("hasCredits") is True or credits.get("unlimited") is True:
            raise ImageError(EXTRA_CREDITS)
        if credits.get("hasCredits") is not False or credits.get("unlimited") is not False:
            raise ImageError(CREDIT_STATE_UNKNOWN)
        try:
            balance = Decimal(credits["balance"]) if isinstance(credits.get("balance"), str) else None
        except InvalidOperation:
            balance = None
        if balance is None or not balance.is_finite() or balance < 0:
            raise ImageError(CREDIT_STATE_UNKNOWN)
        if balance > 0:
            raise ImageError(EXTRA_CREDITS)

async def check_before_dispatch(rpc):
    try:
        snapshot = await rpc.call("account/rateLimits/read", {}, timeout=15)
    except Exception:
        raise ImageError(CREDIT_STATE_UNKNOWN) from None
    included_allowance(snapshot)

def result_image(item, expected, thread):
    check_limit((item.get("failure") or {}).get("type"))
    if item.get("status") != "completed" or item.get("failure"):
        raise ImageError(UNCERTAIN)
    observed = item.get("inputImages") or []
    if [(r.get("path"), r.get("sha256")) for r in observed] != list(expected.items()):
        raise ImageError("GPT Image не подтвердил использование всех исходных фото. Автоматического повтора нет.")
    encoded = item.get("result")
    if encoded:
        if not isinstance(encoded, str) or len(encoded) > 4*((images.MAX_IMAGE+2)//3):
            raise ImageError(UNCERTAIN)
        raw = base64.b64decode(encoded, validate=True)
    else:
        # Never follow an agent-proposed path or list output from other sessions.
        thread_dir = ARTIFACTS / str(UUID(thread))
        file = Path(item.get("savedPath") or "")
        if file.parent != thread_dir or file.suffix.lower() not in (".png", ".jpg", ".jpeg") or thread_dir.resolve(strict=True) != thread_dir:
            raise ImageError(UNCERTAIN)
        fd = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as src:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or not 0 < st.st_size <= images.MAX_IMAGE:
                raise ImageError(UNCERTAIN)
            raw = src.read(images.MAX_IMAGE+1)
    if images.validate_image(raw) not in ("image/png", "image/jpeg"):
        raise ImageError(UNCERTAIN)
    return raw
