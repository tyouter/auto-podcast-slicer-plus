"""ffprobe wrapper. Fixes legacy bug #12: used ``eval()`` on ffprobe fps output."""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional

log = logging.getLogger(__name__)

__all__ = ["MediaInfo", "probe_media", "parse_frame_rate"]


@dataclass(frozen=True)
class MediaInfo:
    width: int
    height: int
    duration_s: float
    fps: float
    has_audio: bool
    audio_sample_rate: int = 0


def parse_frame_rate(rate_str: str) -> float:
    """Safely parse an ffprobe ``r_frame_rate`` like ``"30000/1001"``.

    Fixes the legacy ``eval(video_stream.get("r_frame_rate"))`` — never eval.
    """
    rate_str = (rate_str or "0/1").strip()
    try:
        return float(Fraction(rate_str))
    except (ZeroDivisionError, ValueError) as e:
        log.warning("unparseable frame rate %r (%s) — defaulting to 0.0", rate_str, e)
        return 0.0


def probe_media(path: str, ffprobe_bin: str = "ffprobe") -> Optional[MediaInfo]:
    """Probe a media file. Returns None if ffprobe fails or file unreadable."""
    cmd = [
        ffprobe_bin, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                              encoding="utf-8", errors="replace")
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log.error("ffprobe failed for %s: %s", path, e)
        return None
    if proc.returncode != 0:
        log.error("ffprobe nonzero exit for %s: %s", path, proc.stderr[:200])
        return None

    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as e:
        log.error("ffprobe returned non-JSON for %s: %s", path, e)
        return None

    streams = data.get("streams", []) or []
    vstream = next((s for s in streams if s.get("codec_type") == "video"), None)
    astream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if vstream is None and astream is None:
        log.warning("no video or audio stream in %s", path)
        return None

    fmt = data.get("format", {}) or {}
    duration = 0.0
    # Prefer format duration, then stream duration (video or audio).
    for src in (fmt.get("duration"),
                vstream.get("duration") if vstream else None,
                astream.get("duration") if astream else None):
        try:
            if src is not None:
                duration = float(src)
                break
        except (TypeError, ValueError):
            pass

    fps = parse_frame_rate(vstream.get("r_frame_rate", "0/1")) if vstream else 0.0
    return MediaInfo(
        width=int(vstream.get("width", 0)) if vstream else 0,
        height=int(vstream.get("height", 0)) if vstream else 0,
        duration_s=duration,
        fps=fps,
        has_audio=astream is not None,
        audio_sample_rate=int(astream.get("sample_rate", 0)) if astream else 0,
    )
