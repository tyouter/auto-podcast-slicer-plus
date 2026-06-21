"""Stage 5: clip selection (cues + cut points → ClipPlan).

Clips are parametric objects (source-ref + in/out + cues + style), not bytes.
"""

from __future__ import annotations

from garden_core.types import ClipPlan, Cue, CutPoint, Transcript

__all__ = ["cut"]


def cut(
    transcript: Transcript,
    cues: tuple[Cue, ...],
    cut_points: list[CutPoint],
) -> tuple[ClipPlan, ...]:
    """Run stage 5: build a ClipPlan per CutPoint from the source timeline.

    Cues overlapping a clip window are included and rebased to clip-local time.
    """
    plans: list[ClipPlan] = []
    for cp in cut_points:
        local_cues: list[Cue] = []
        for cue in cues:
            # Include a cue if its span overlaps the clip window.
            if cue.end_s <= cp.start_s or cue.start_s >= cp.end_s:
                continue
            local_start = max(0.0, cue.start_s - cp.start_s)
            local_end = min(cp.end_s - cp.start_s, cue.end_s - cp.start_s)
            local_cues.append(Cue(
                index=len(local_cues),
                text=cue.text,
                start_s=local_start,
                end_s=local_end,
                text_en=cue.text_en,
            ))
        plans.append(ClipPlan(
            clip_id=cp.clip_id,
            source_ref=transcript.source_file,
            start_s=cp.start_s,
            end_s=cp.end_s,
            cues=tuple(local_cues),
            style_name=cp.style_name,
            title=cp.title,
        ))
    return tuple(plans)
