"""ffmpeg rendering: horizontal + vertical mp4 with burned-in subtitles.

Rewritten from legacy clip_processor.generate_video_subtitled /
generate_video_vertical. The vertical blur-fill overlay chain is kept verbatim
(it worked well); the horizontal path is a straightforward subtitle burn-in.

Rendering is the ONE place stages touch ffmpeg / write mp4 — everything else
is pure. Failures are returned as empty strings with a logged error (never a
silent false-pass): the caller's RenderResult will show missing paths.
"""

from __future__ import annotations

import gc
import logging
import os
import subprocess
from pathlib import Path

from garden_core.stage_render import RenderOptions
from garden_core.types import ClipPlan, StyleDef

log = logging.getLogger(__name__)

__all__ = ["render_horizontal", "render_vertical", "escape_ass_path"]


def escape_ass_path(path: str) -> str:
    """Escape an ASS subtitles= path for the ffmpeg filtergraph.

    Windows drive colons must be escaped (``C:\\`` → ``C\\:``) and backslashes
    flipped to forward slashes. Carried over from legacy — this was a real bug
    source, so it's centralized here.
    """
    return path.replace("\\", "/").replace(":", "\\:")


def _run_ffmpeg(cmd: list[str], output_path: str, timeout_s: int) -> str:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout_s
        )
    except subprocess.TimeoutExpired:
        log.error("ffmpeg timed out for %s", output_path)
        if os.path.exists(output_path):
            os.remove(output_path)
        return ""
    except FileNotFoundError:
        log.error("ffmpeg binary not found on PATH")
        return ""
    gc.collect()
    if result.returncode != 0 or not os.path.exists(output_path):
        log.error("ffmpeg failed (%s): %s", result.returncode, (result.stderr or "")[-500:])
        if os.path.exists(output_path):
            os.remove(output_path)
        return ""
    return output_path


def _common_output(clip: ClipPlan, opts: RenderOptions, suffix: str) -> str:
    return os.path.join(opts.output_dir, f"{clip.clip_id}_{suffix}.mp4")


def render_horizontal(
    clip: ClipPlan, ass_path: str, style: StyleDef, opts: RenderOptions
) -> str:
    """Burn subtitles onto a horizontal (16:9) clip. Returns mp4 path or ''."""
    out = _common_output(clip, opts, "horizontal")
    w, h = opts.horizontal_width, opts.horizontal_height
    escaped = escape_ass_path(ass_path)
    vf = f"subtitles='{escaped}':fontsdir='C\\:/Windows/Fonts',scale={w}:{h}"
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(clip.start_s), "-to", str(clip.end_s),
        "-i", clip.source_ref,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", str(opts.crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        out,
    ]
    timeout = max(600, int(clip.duration_s * 2))
    return _run_ffmpeg(cmd, out, timeout)


def render_vertical(
    clip: ClipPlan, ass_path: str, style: StyleDef, opts: RenderOptions
) -> str:
    """Vertical (9:16) with blurred source as background, foreground centered.

    Filter chain (faithful to the legacy vertical renderer):
        split → [bg] scale-cover + boxblur (fill) ;
                [fg] scale to vertical_width ;
                overlay centered → subtitles
    """
    out = _common_output(clip, opts, "vertical")
    vw, vh = opts.vertical_width, opts.vertical_height
    escaped = escape_ass_path(ass_path)
    vf_chain = (
        f"split[bg][fg];"
        f"[bg]scale={vw}:{vh}:force_original_aspect_ratio=increase,"
        f"crop={vw}:{vh},boxblur=40[blurred];"
        f"[fg]scale={vw}:-2[scaled];"
        f"[blurred][scaled]overlay=(W-w)/2:(H-h)/2[v];"
        f"[v]subtitles='{escaped}':fontsdir='C\\:/Windows/Fonts'"
    )
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(clip.start_s), "-to", str(clip.end_s),
        "-i", clip.source_ref,
        "-vf", vf_chain,
        "-c:v", "libx264", "-preset", "medium", "-b:v", "5000k",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        out,
    ]
    timeout = max(600, int(clip.duration_s * 2))
    return _run_ffmpeg(cmd, out, timeout)
