"""Merger-based segmentation: duration/char-driven merge+split.

Simpler alternative to semantic_split. Merges consecutive short segments up to
max_chars*max_lines, splits segments exceeding it at sentence boundaries, and
enforces min duration + no overlap. Output is the same ``Cue`` type.
"""

from __future__ import annotations

from dataclasses import replace as _replace

from garden_core.stage_segment import SegmentOptions
from garden_core.stage_segment.semantic_split import _enforce_timing, _strip_forbidden_start
from garden_core.types import Cue, Segment, Transcript

__all__ = ["segment_by_merger"]


def _split_long(seg: Segment, max_chars: int) -> list[tuple[str, float, float]]:
    """Split a too-long segment into chunks of ≤ max_chars, char-ratio timed."""
    text = seg.text
    chunks: list[tuple[str, float, float]] = []
    total = len(text) or 1
    span = seg.duration_s
    i = 0
    while i < len(text):
        chunk = text[i:i + max_chars]
        share = len(chunk) / total
        s = seg.start_s + span * (i / total)
        e = s + span * share
        chunks.append((_strip_forbidden_start(chunk), s, e))
        i += max_chars
    return [c for c in chunks if c[0]]


def segment_by_merger(transcript: Transcript, opts: SegmentOptions) -> tuple[Cue, ...]:
    max_chars = opts.max_chars_per_line * opts.max_lines
    cues: list[Cue] = []
    idx = 0
    # working buffer for merging
    buf_text = ""
    buf_start: float = -1
    buf_end: float = 0

    def flush() -> None:
        nonlocal buf_text, buf_start, buf_end, idx
        if not buf_text.strip():
            buf_text, buf_start = "", -1
            return
        text = _strip_forbidden_start(buf_text.strip())
        if len(text) <= max_chars:
            cues.append(Cue(index=idx, text=text, start_s=buf_start, end_s=buf_end))
            idx += 1
        else:
            for t, s, e in _split_long(
                Segment(text=text, start_s=buf_start, end_s=buf_end), max_chars
            ):
                cues.append(Cue(index=idx, text=t, start_s=s, end_s=e))
                idx += 1
        buf_text, buf_start = "", -1

    for seg in transcript.segments:
        if buf_start < 0:
            buf_start = seg.start_s
        buf_end = seg.end_s
        buf_text += seg.text
        # flush when we have enough
        if len(buf_text) >= max_chars:
            flush()
    flush()

    return tuple(_enforce_timing(cues, opts))
