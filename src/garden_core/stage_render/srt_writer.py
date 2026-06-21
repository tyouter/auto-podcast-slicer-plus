"""SRT generation. Pure string building, seconds→SRT time via time_util."""

from __future__ import annotations

from garden_core.infra.time_util import format_srt_time
from garden_core.types import ClipPlan

__all__ = ["build_srt"]


def build_srt(clip: ClipPlan) -> str:
    """Build an SRT document for a clip (clip-relative time, starting at 0)."""
    lines: list[str] = []
    for i, cue in enumerate(clip.cues, start=1):
        if not cue.text.strip():
            continue
        lines.append(str(i))
        lines.append(f"{format_srt_time(cue.start_s)} --> {format_srt_time(cue.end_s)}")
        lines.append(cue.text)
        lines.append("")  # blank line separates entries
    return "\n".join(lines)
