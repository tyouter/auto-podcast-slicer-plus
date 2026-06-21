"""Single source of truth for time conversions and formatting.

Fixes legacy bug #11: ASS time parse/format was duplicated and fragile
(``.replace('.', ':')`` assumed strict H:MM:SS.cc). Here one module owns it.
"""

from __future__ import annotations

__all__ = [
    "ms_to_s",
    "s_to_ms",
    "format_ass_time",
    "parse_ass_time",
    "format_srt_time",
    "parse_time_heuristic",
]


def ms_to_s(ms: float) -> float:
    return ms / 1000.0


def s_to_ms(s: float) -> float:
    return s * 1000.0


def format_ass_time(seconds: float) -> str:
    """Format seconds as ASS timestamp ``H:MM:SS.cc`` (centisecond precision).

    ASS uses centiseconds, not milliseconds, so we round to 2 decimals.
    """
    if seconds < 0:
        seconds = 0.0
    total_cs = round(seconds * 100.0)
    # 1 hour = 3600 s = 360_000 centiseconds; 1 min = 60 s = 6000 cs.
    hours, rem = divmod(total_cs, 360_000)
    minutes, rem = divmod(rem, 6000)
    secs, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def parse_ass_time(text: str) -> float:
    """Parse ``H:MM:SS.cc`` (or ``H:MM:SS.cc`` with ':' for cs) → seconds.

    Tolerant: accepts both ``.`` and ``:`` as the centisecond separator and
    a single-digit hour field.
    """
    text = text.strip()
    # Normalise the centisecond separator to '.'.
    # Format is H:MM:SS<sep>cc — split off the first two ':' as field separators.
    parts = text.split(":")
    if len(parts) != 4:
        # H:MM:SS.cc form (3 fields)
        if len(parts) == 3:
            h, m, rest = parts
            if "." in rest:
                s, cs = rest.split(".", 1)
            else:
                # already collapsed; treat whole as seconds
                s, cs = rest, "0"
        else:
            raise ValueError(f"unrecognised ASS time: {text!r}")
    else:
        # H:MM:SS:cc form
        h, m, s, cs = parts
    return int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100.0


def format_srt_time(seconds: float) -> str:
    """Format seconds as SRT timestamp ``HH:MM:SS,mmm``."""
    if seconds < 0:
        seconds = 0.0
    total_ms = round(seconds * 1000.0)
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def parse_time_heuristic(value, source_hint: str = "") -> float:
    """Best-effort interpret a raw time value as seconds.

    Legacy ASR JSON used inconsistent keys (``start``/``begin``/``start_ms``).
    Used only at the I/O boundary when ingesting foreign JSON. Heuristic:
      * float/int >= 100_000  → milliseconds
      * float/int <  100_000  → seconds
    """
    if isinstance(value, str):
        value = float(value)
    value = float(value)
    if value >= 100_000.0:  # 100000 ms == 100 s; any sane seconds value is smaller
        return value / 1000.0
    return value
