"""Stage 4: subtitle segmentation (Transcript[Segment] → tuple[Cue, ...]).

Fixes legacy dual-implementation bug: subtitle_merger (ms-based) and
subtitle_formatter.segment_subtitle_entries (seconds-based) were two parallel
segmenters. Here there is ONE output type (``Cue``) and the strategy is chosen
via ``SegmentOptions.strategy``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from garden_core.types import Cue, Transcript

__all__ = ["SegmentOptions", "segment"]


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
        return segment_by_merger(transcript, opts)
    from garden_core.stage_segment.semantic_split import segment_by_semantic
    return segment_by_semantic(transcript, opts)
