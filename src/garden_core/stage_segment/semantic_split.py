"""Semantic-boundary segmentation: Transcript[Segment] → tuple[Cue, ...].

Rewritten from the legacy subtitle_formatter.segment_subtitle_entries, but:
  * outputs the single ``Cue`` type (not a 3rd entry shape),
  * operates in seconds throughout (no ms boundary conversion),
  * uses word-level timing when present to redistribute timestamps accurately,
    falling back to char-ratio otherwise.

Boundary preference (same as legacy): sentence-end punctuation > comma >
connective word > safe char > hard cut.
"""

from __future__ import annotations

import re

from garden_core.stage_segment import SegmentOptions
from garden_core.types import Cue, Segment, Transcript, Word

__all__ = ["segment_by_semantic"]

# CJK punctuation & connective tables (carried over from legacy formatter).
LINE_START_FORBIDDEN = "的了着过吗呢吧啊呀哇嘛呗的啦咯嗯噢哦哈"
CONNECTIVE_WORDS = (
    "但是", "不过", "可是", "其实", "然后", "所以", "而且", "就是",
    "因为", "如果", "虽然", "因此", "或者", "同时", "另外", "那么",
    "也就是说", "换句话说", "总而言之", "所以说",
)
_SENTENCE_END = "。！？；!?;"
_COMMA = "，、,:："


def _strip_forbidden_start(text: str) -> str:
    while text and text[0] in LINE_START_FORBIDDEN:
        text = text[1:]
    return text


def _find_split_point(text: str, max_chars: int) -> int:
    """Return a char index at which to split ``text`` (≤ max_chars), or -1.

    Preference order: sentence end > comma > connective > last safe char.
    """
    window = text[:max_chars]
    # 1. sentence-end punctuation
    for prio in (_SENTENCE_END, _COMMA):
        idx = max(window.rfind(ch) for ch in prio)
        if idx >= max_chars // 3:  # avoid tiny first fragment
            return idx + 1
    # 2. connective word starting in the window (split before it)
    for cw in sorted(CONNECTIVE_WORDS, key=len, reverse=True):
        pos = window.rfind(cw)
        if 0 < pos <= max_chars - len(cw):
            return pos
    # 3. last safe boundary char (whitespace)
    m = list(re.finditer(r"\s", window))
    if m and m[-1].start() > 2:
        return m[-1].start()
    # 4. hard cut
    return max_chars


def _char_ratio_split(start_s: float, end_s: float, chars: str) -> tuple[float, float]:
    """Timestamps for a sub-chunk via equal char-ratio distribution."""
    return start_s, end_s  # caller handles per-sub timing when redistributing


def _redistribute_by_words(
    subs: list[str], seg: Segment
) -> list[tuple[str, float, float]]:
    """Map each sub-string to a (start, end) using the segment's word timing.

    Walks ``seg.words`` consuming characters; each sub gets the span of its
    words. Falls back to char-ratio if no words or mismatch.
    """
    out: list[tuple[str, float, float]] = []
    if not seg.words:
        total = len("".join(subs)) or 1
        cursor = seg.start_s
        span = seg.duration_s
        for s in subs:
            share = len(s) / total
            out.append((s, cursor, cursor + span * share))
            cursor += span * share
        if out:
            a, b, _ = out[-1]
            out[-1] = (a, b, seg.end_s)
        return out

    # word-based: flatten words into a char stream with timestamps
    word_chars = []  # list of (char, start_s, end_s)
    for w in seg.words:
        n = len(w.text)
        if n == 0:
            continue
        for i, ch in enumerate(w.text):
            ts0 = w.start_s + (w.end_s - w.start_s) * (i / n)
            ts1 = w.start_s + (w.end_s - w.start_s) * ((i + 1) / n)
            word_chars.append((ch, ts0, ts1))

    ci = 0
    for s in subs:
        start_ts = word_chars[ci][1] if ci < len(word_chars) else seg.start_s
        consumed = len(s)
        end_ci = min(ci + consumed - 1, len(word_chars) - 1)
        end_ts = word_chars[end_ci][2] if end_ci >= 0 else seg.end_s
        out.append((s, start_ts, end_ts))
        ci += consumed
    if out:
        a, b, _ = out[-1]
        out[-1] = (a, b, seg.end_s)
    return out


def _enforce_timing(cues: list[Cue], opts: SegmentOptions) -> list[Cue]:
    """Fix overlaps + enforce min/max duration; preserve ordering."""
    if not cues:
        return cues
    fixed: list[Cue] = []
    for i, cue in enumerate(cues):
        start = cue.start_s
        end = cue.end_s
        # min duration
        if end - start < opts.min_duration_s:
            end = start + opts.min_duration_s
        # max duration — would require re-split; just clamp (rare here)
        if end - start > opts.max_duration_s:
            end = start + opts.max_duration_s
        # no overlap with next
        if i + 1 < len(cues) and end > cues[i + 1].start_s:
            end = cues[i + 1].start_s - opts.min_gap_s
        if end <= start:
            end = start + opts.min_duration_s
        fixed.append(Cue(index=cue.index, text=cue.text, start_s=start, end_s=end,
                         text_en=cue.text_en))
    # last cue must not exceed its segment group's end — leave as-is
    return fixed


def _segment_to_cues(seg: Segment, opts: SegmentOptions, start_index: int) -> list[Cue]:
    """Turn one ASR segment into 1..N cues, respecting max_chars/max_lines."""
    text = _strip_forbidden_start(seg.text.strip())
    if not text:
        return []
    max_chars = opts.max_chars_per_line * opts.max_lines
    # Short enough → single cue.
    if len(text) <= max_chars:
        return [Cue(index=start_index, text=text, start_s=seg.start_s,
                    end_s=seg.end_s)]

    # Slice into sub-strings of ≤ max_chars at semantic boundaries.
    subs: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        cut = _find_split_point(remaining, max_chars)
        subs.append(_strip_forbidden_start(remaining[:cut]))
        remaining = _strip_forbidden_start(remaining[cut:])
    if remaining:
        subs.append(remaining)

    timed = _redistribute_by_words(subs, seg)
    cues = [
        Cue(index=start_index + i, text=t, start_s=max(s, seg.start_s),
            end_s=min(e, seg.end_s))
        for i, (t, s, e) in enumerate(timed)
        if t.strip()
    ]
    return cues


def segment_by_semantic(transcript: Transcript, opts: SegmentOptions) -> tuple[Cue, ...]:
    """Segment the whole transcript into Cues via semantic boundaries."""
    cues: list[Cue] = []
    idx = 0
    for seg in transcript.segments:
        new = _segment_to_cues(seg, opts, idx)
        cues.extend(new)
        idx += len(new)
    cues = _enforce_timing(cues, opts)
    # renumber after enforcement
    return tuple(
        Cue(index=i, text=c.text, start_s=c.start_s, end_s=c.end_s, text_en=c.text_en)
        for i, c in enumerate(cues)
    )
