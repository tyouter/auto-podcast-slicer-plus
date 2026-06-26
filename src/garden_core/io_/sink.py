"""Writers: typed artifacts → files. Only here do we write to disk."""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path

from garden_core.types import Transcript

__all__ = ["ensure_dir", "write_text_file", "write_json_file", "save_transcript_json"]


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


def save_transcript_json(transcript: Transcript, path: str | Path) -> str:
    """Serialize a Transcript to JSON, symmetric with load_transcript_json.

    Uses ``dataclasses.asdict`` (Transcript is frozen) so the nested
    Segment/Word structure is written in the seconds-based shape that
    ``io_/source.py::load_transcript_json`` reads back. Overwrites if the file
    already exists (idempotent).
    """
    return write_json_file(path, dataclasses.asdict(transcript))
