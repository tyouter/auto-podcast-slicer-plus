"""Stage 4: subtitle segmentation (Transcript[Segment] → tuple[Cue, ...]).

Fixes legacy dual-implementation bug: subtitle_merger (ms-based) and
subtitle_formatter.segment_subtitle_entries (seconds-based) were two parallel
segmenters. Here there is ONE output type (``Cue``) and the strategy is chosen
via ``SegmentOptions.strategy``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from garden_core.types import Cue, Transcript, replace

__all__ = ["SegmentOptions", "segment"]

# Defensive cue filter: dirty transcript rows (e.g. {"text": "SPK1:"} or a bare
# "，") get passed through as standalone cues and rendered as on-screen junk.
# A cue earns its place on screen only if it carries actual content.
_SPEAKER_TAG_RE = re.compile(r"SPK\d+\s*[:：]?", re.IGNORECASE)


def _is_content_cue(text: str) -> bool:
    """True unless the cue is a pure speaker label or pure punctuation/whitespace."""
    t = text.strip()
    if not t:
        return False  # pure whitespace
    if _SPEAKER_TAG_RE.fullmatch(t):
        return False  # pure speaker tag, e.g. "SPK1:" / "SPK0："
    if not any(ch.isalnum() for ch in t):
        return False  # nothing left after stripping punctuation, e.g. "，"
    return True


def _drop_noise_cues(cues: tuple[Cue, ...]) -> tuple[Cue, ...]:
    """Drop non-content cues and renumber the survivors to stay contiguous."""
    kept = [c for c in cues if _is_content_cue(c.text)]
    if len(kept) == len(cues):
        return tuple(cues)
    return tuple(replace(c, index=i) for i, c in enumerate(kept))


@dataclass(frozen=True)
class SegmentOptions:
    strategy: Literal["merger", "semantic"] = "semantic"
    max_chars_per_line: int = 14
    max_lines: int = 2
    max_duration_s: float = 7.0
    min_duration_s: float = 1.0
    reading_speed: float = 4.0  # chars/sec reading-speed cap
    min_gap_s: float = 0.05


def segment(transcript: Transcript, opts: SegmentOptions) -> tuple[Cue, ...]:
    """Run stage 4: turn the timeline into a sequence of subtitle cues."""
    if opts.strategy == "merger":
        from garden_core.stage_segment.merger import segment_by_merger
        cues = segment_by_merger(transcript, opts)
    else:
        from garden_core.stage_segment.semantic_split import segment_by_semantic
        cues = segment_by_semantic(transcript, opts)
    return _drop_noise_cues(cues)
