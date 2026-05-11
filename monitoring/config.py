from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _deep_merge(base: Any, override: Any) -> Any:
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override

    merged = dict(base)
    for key, value in override.items():
        merged[key] = _deep_merge(merged.get(key), value)
    return merged


def default_config_path() -> Path:
    return Path(__file__).with_name("default_config.json")


def load_config(path: str | None = None) -> dict:
    with default_config_path().open("r", encoding="utf-8") as fh:
        default_cfg = json.load(fh)

    if not path:
        return default_cfg

    user_path = Path(path)
    with user_path.open("r", encoding="utf-8") as fh:
        user_cfg = json.load(fh)

    return _deep_merge(default_cfg, user_cfg)

