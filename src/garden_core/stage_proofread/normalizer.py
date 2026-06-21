"""Normalizer: 繁→简 conversion + 著→着.

Rewritten from legacy text_normalizer.py, but stateless (no module globals).
OpenCC is loaded lazily and cached; the 著→着 protect-list is a constant.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Tuple

from garden_core.types import Segment, Transcript

log = logging.getLogger(__name__)

__all__ = ["normalize_segments", "traditional_to_simplified", "convert_zhu_to_zhe"]

# Compounds where 著 must NOT become 着 (carried over from legacy).
ZHU_KEEP_COMPOUNDS: Tuple[str, ...] = (
    "著名", "著作", "著者", "显著", "卓著", "原著", "译著", "编著", "论著",
    "著录", "专著", "巨著", "名著", "遗著", "新著", "合著", "著述",
)


@lru_cache(maxsize=1)
def _opencc_t2s():
    try:
        from opencc import OpenCC  # type: ignore
        return OpenCC("t2s")
    except Exception:
        log.info("OpenCC unavailable —繁简转换 will be a no-op")
        return None


def traditional_to_simplified(text: str) -> str:
    cc = _opencc_t2s()
    return cc.convert(text) if cc else text


def convert_zhu_to_zhe(text: str) -> str:
    """Replace 著→着 except inside ZHU_KEEP_COMPOUNDS (placeholders protect them)."""
    placeholders: dict[str, str] = {}
    protected = text
    for i, compound in enumerate(ZHU_KEEP_COMPOUNDS):
        token = f"\x00ZK{i}\x00"
        if compound in protected:
            placeholders[token] = compound
            protected = protected.replace(compound, token)
    protected = protected.replace("著", "着")
    for token, compound in placeholders.items():
        protected = protected.replace(token, compound)
    return protected


def normalize_text(text: str) -> str:
    return convert_zhu_to_zhe(traditional_to_simplified(text))


def normalize_segments(transcript: Transcript) -> Tuple[Transcript, int]:
    """Apply 繁简 + 著着 normalization to every segment. Returns (new, count)."""
    from dataclasses import replace as _replace
    changed = 0
    new_segs: list[Segment] = []
    for seg in transcript.segments:
        nt = normalize_text(seg.text)
        if nt != seg.text:
            changed += 1
        new_segs.append(_replace(seg, text=nt))
    return _replace(transcript, segments=tuple(new_segs)), changed
