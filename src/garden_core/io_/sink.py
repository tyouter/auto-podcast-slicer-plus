"""Writers: typed artifacts → files. Only here do we write to disk."""

from __future__ import annotations

import json
import os
from pathlib import Path

__all__ = ["ensure_dir", "write_text_file", "write_json_file"]


def ensure_dir(path: str | Path) -> None:
    os.makedirs(path, exist_ok=True)


def write_text_file(path: str | Path, text: str) -> str:
    path = str(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def write_json_file(path: str | Path, obj: dict) -> str:
    return write_text_file(path, json.dumps(obj, ensure_ascii=False, indent=2))
