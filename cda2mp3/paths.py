"""资源路径定位(兼容 PyInstaller onefile)。"""
from __future__ import annotations

import sys
from pathlib import Path


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


def resource_path(rel: str) -> str:
    return str(base_dir() / rel)
