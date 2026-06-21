"""Errata: deterministic text corrections (apply-only).

Fixes the legacy errata/content_validator name collision: this module ONLY
applies corrections (never detects). Detection lives in ``phonetic.py``.

The ``ErrataConfig`` comes from ``stage_proofread`` (built by config.py from a
project errata.yaml). Corrections are applied longest-first to avoid partial
substitutions, and regex patterns run after the literal map.
"""

from __future__ import annotations

import logging
from typing import Tuple

from garden_core.stage_proofread import ErrataConfig
from garden_core.types import Segment, Transcript

log = logging.getLogger(__name__)

__all__ = ["apply_errata_to_segments"]


def apply_to_text(text: str, errata: ErrataConfig) -> tuple[str, int]:
    """Apply flat literal corrections + regex patterns. Returns (text, n_changes)."""
    if not errata.flat and not errata.patterns:
        return text, 0
    changed = 0
    out = text
    # longest-first so e.g. "小径分岔" is replaced before "小径"
    for wrong, correct in sorted(errata.flat.items(), key=lambda kv: -len(kv[0])):
        if wrong and wrong in out:
            count = out.count(wrong)
            out = out.replace(wrong, correct)
            changed += count
    for pattern, replacement in errata.patterns:
        new_out, n = pattern.subn(replacement, out)
        if n:
            out = new_out
            changed += n
    return out, changed


def apply_errata_to_segments(
    transcript: Transcript, errata: ErrataConfig,
) -> Tuple[Transcript, int]:
    """Apply errata to every segment. Returns (new transcript, total changes)."""
    from dataclasses import replace as _replace
    total = 0
    new_segs: list[Segment] = []
    for seg in transcript.segments:
        nt, n = apply_to_text(seg.text, errata)
        total += n
        new_segs.append(_replace(seg, text=nt) if n else seg)
    return _replace(transcript, segments=tuple(new_segs)), total
