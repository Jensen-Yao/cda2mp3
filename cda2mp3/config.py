"""应用配置持久化(%LOCALAPPDATA%/cda2mp3/config.json)。"""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "cda2mp3"
CONFIG_FILE = CONFIG_DIR / "config.json"

_DEFAULTS = {
    "out_dir": "",
    "bitrate": 320,
    "template": "{track:02d}. {title}",
    "verify": False,
    "write_tags": True,
    "last_drive": "",
    "volume": 0.85,
    "year": "",
    "genre": "",
}


def load_config() -> dict:
    cfg = dict(_DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_FILE.read_text("utf-8")))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        keep = {k: cfg.get(k, v) for k, v in _DEFAULTS.items()}
        CONFIG_FILE.write_text(json.dumps(keep, ensure_ascii=False, indent=2), "utf-8")
    except OSError:
        pass
