"""Настройки из .env проекта (секреты не печатаются)."""

import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW_ARCHIVE = DATA / "raw"


@lru_cache
def env() -> dict:
    out = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("\"'")
    out.update(os.environ)
    return out


def get(key: str) -> str:
    v = env().get(key)
    if not v:
        raise SystemExit(f"{key} нет в .env")
    return v


def today_msk():
    """Сегодня по Москве: WB отдаёт даты в МСК, «вчера» в дашбордах — московское (сервер живёт в UTC)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Europe/Moscow")).date()


def site_url():
    return env().get("SITE_URL", "http://localhost:8100").rstrip("/")
