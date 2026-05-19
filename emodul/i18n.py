"""Cache the eModul translation dictionary so we can resolve txtId references."""
from __future__ import annotations

import json
from pathlib import Path

from emodul.api import ApiClient
from emodul.config import _config_dir


def _cache_path(lang: str) -> Path:
    return _config_dir() / f"i18n_{lang}.json"


def load_dictionary(lang: str) -> dict[str, str]:
    p = _cache_path(lang)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        return json.load(f).get("data", {})


def refresh_dictionary(api: ApiClient, lang: str) -> dict[str, str]:
    body = api.i18n(lang)
    p = _cache_path(lang)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False)
    return body.get("data", {})


def get_or_refresh(api: ApiClient, lang: str) -> dict[str, str]:
    d = load_dictionary(lang)
    if d:
        return d
    return refresh_dictionary(api, lang)


def lookup(dictionary: dict[str, str], txt_id: int | str | None, fallback: str = "") -> str:
    if txt_id is None:
        return fallback
    return dictionary.get(str(txt_id), fallback)
