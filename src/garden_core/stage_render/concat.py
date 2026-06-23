"""Lossless join of already-rendered clips into one continuous video.

Borrowed from the legacy ``pipeline/multi_segment.py:_ffmpeg_concat`` and adapted
to garden-core conventions (return the output path or '' + a loud log, like
``ffmpeg_render``). Uses ffmpeg's concat *demuxer* with stream copy: this is
valid only when every input shares identical codec parameters — which holds
here because the montage renders all sub-clips through the SAME RenderOptions.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

__all__ = ["concat_videos"]


def concat_videos(inputs: list[str], output: str, timeout_s: int = 1800) -> str:
    """Concat ``inputs`` (in order) into ``output`` via stream copy.

    Returns the output path on success, or '' on failure (logged). The concat
    list file uses forward-slash absolute paths so Windows backslashes never
    need escaping inside the demuxer's ``file '...'`` directive.
    """
    if not inputs:
        log.error("concat_videos: no inputs")
        return ""

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    concat_list = out_path.parent / f"_concat_{out_path.stem}.txt"
    try:
        with open(concat_list, "w", encoding="utf-8") as fh:
            for p in inputs:
                fh.write(f"file '{Path(p).resolve().as_posix()}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            str(out_path),
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        log.error("concat_videos timed out for %s", output)
        if out_path.exists():
            out_path.unlink()
        return ""
    except FileNotFoundError:
        log.error("ffmpeg binary not found on PATH")
        return ""
    finally:
        try:
            concat_list.unlink(missing_ok=True)
        except OSError:
            pass

    if result.returncode != 0 or not out_path.exists():
        log.error("concat failed (%s): %s", result.returncode, (result.stderr or "")[-500:])
        if out_path.exists():
            os.remove(out_path)
        return ""
    return str(out_path)
