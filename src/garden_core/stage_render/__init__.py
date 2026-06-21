"""Stage 7: render (ClipPlan + StyleDef → RenderResult).

ASS generation (ass_writer) is pure string building — no side effects — so it
can be unit-tested without ffmpeg. ffmpeg_render consumes the .ass and the
source video to produce horizontal + vertical mp4.

Each orientation gets its OWN .ass, sized to that orientation's target canvas
height (NOT the source video height). This matters when the source is 4K but
we render to 720p/1080×1920: the ASS must be authored at the render resolution
so font sizes and box geometry are correct.
"""

from __future__ import annotations

import os

from garden_core.types import ClipPlan, RenderResult, StyleDef

__all__ = ["RenderOptions", "render"]


class RenderOptions:
    """Mutable-ish options container (kept a plain class for ergonomics)."""

    def __init__(
        self,
        output_dir: str,
        render_horizontal: bool = True,
        render_vertical: bool = True,
        vertical_height: int = 1920,
        vertical_width: int = 1080,
        horizontal_height: int = 1080,
        horizontal_width: int = 1920,
        crf: int = 18,
    ) -> None:
        self.output_dir = output_dir
        self.render_horizontal = render_horizontal
        self.render_vertical = render_vertical
        self.vertical_height = vertical_height
        self.vertical_width = vertical_width
        self.horizontal_height = horizontal_height
        self.horizontal_width = horizontal_width
        self.crf = crf


def render(clip: ClipPlan, style: StyleDef, opts: RenderOptions) -> RenderResult:
    """Run stage 7: write per-orientation ASS + SRT, then render mp4s."""
    from garden_core.io_.sink import ensure_dir, write_text_file
    from garden_core.stage_render.ass_writer import build_ass
    from garden_core.stage_render.srt_writer import build_srt
    from garden_core.stage_render.ffmpeg_render import render_horizontal, render_vertical

    ensure_dir(opts.output_dir)

    # SRT is orientation-independent.
    srt_text = build_srt(clip)
    srt_path = os.path.join(opts.output_dir, f"{clip.clip_id}.srt")
    write_text_file(srt_path, srt_text)

    # The default .ass (canonical) is authored at horizontal resolution.
    ass_path = os.path.join(opts.output_dir, f"{clip.clip_id}.ass")
    write_text_file(ass_path, build_ass(clip, style, opts.horizontal_height))

    h_mp4 = ""
    v_mp4 = ""
    if opts.render_horizontal:
        h_mp4 = render_horizontal(clip, ass_path, style, opts)
    if opts.render_vertical:
        # Vertical gets its own ASS authored at the vertical canvas height.
        v_ass_path = os.path.join(opts.output_dir, f"{clip.clip_id}_vertical.ass")
        write_text_file(v_ass_path, build_ass(
            clip, style, opts.vertical_height, opts.vertical_width,
        ))
        v_mp4 = render_vertical(clip, v_ass_path, style, opts)

    return RenderResult(
        clip_id=clip.clip_id,
        horizontal_mp4=h_mp4,
        vertical_mp4=v_mp4,
        srt_path=srt_path,
        ass_path=ass_path,
        metadata={"style": style.name, "cues": len(clip.cues)},
    )
